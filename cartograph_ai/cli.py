"""Typer CLI for ``cartograph-ai``.

The CLI is a thin wrapper over ``cartograph_ai.probe``.  Flags map
directly to ``ProbeOptions``; rich terminal output mirrors the example
shown in the README, and ``--json`` emits the structured ``ProbeResult``
for machine consumption.
"""

from __future__ import annotations

import json as json_module
import logging
import sys
from urllib.parse import urlparse

import typer
from rich.console import Console

from cartograph_ai import (
    ProbeOptions,
    ProbeResult,
    __version__,
    probe,
)
from cartograph_ai.exceptions import CartographError
from cartograph_ai.stages.claude_classify import DEFAULT_MODEL

app = typer.Typer(
    name="cartograph-ai",
    add_completion=False,
    help=(
        "Probe before extract. Classify how a URL serves data and "
        "recommend the optimal extraction strategy."
    ),
    rich_markup_mode="rich",
)

stdout_console = Console()
stderr_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"cartograph-ai {__version__}")
        raise typer.Exit()


def _configure_logging(debug: bool) -> None:
    """Route cartograph logs to stderr; bump verbosity when --debug is on."""
    level = logging.DEBUG if debug else logging.WARNING
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    fmt = "%(levelname)s %(name)s: %(message)s"
    handler.setFormatter(logging.Formatter(fmt))
    logger = logging.getLogger("cartograph_ai")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.9:
        return "very high"
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.5:
        return "moderate"
    if confidence >= 0.25:
        return "low"
    return "very low"


def _print_rich(result: ProbeResult, *, verbose: bool) -> None:
    """Render the result in the tree-style format the README shows."""
    display = urlparse(result.url).hostname or result.url
    path = urlparse(result.url).path or "/"
    if path != "/":
        display = f"{display}{path}"

    classification_label = (
        result.classification.subcategory
        or result.classification.category
        or "unknown"
    )
    conf = result.classification.confidence
    confidence_label = _confidence_label(conf)

    stdout_console.print(f"[bold]{display}[/bold]")
    stdout_console.print(
        f"[bold cyan]└── {classification_label}[/bold cyan] "
        f"(confidence: {confidence_label}, {conf:.2f})"
    )
    stdout_console.print(f"    [dim]{result.classification.reasoning}[/dim]")

    strategy = result.extraction_strategy
    requests_label = (
        "requests: unknown"
        if strategy.estimated_requests is None
        else f"~{strategy.estimated_requests} request(s)"
    )
    stdout_console.print(
        f"    [green]Recommended:[/green] {strategy.method} "
        f"(tool: {strategy.recommended_tool}, "
        f"{requests_label}, "
        f"browser: {'yes' if strategy.requires_browser else 'no'})"
    )

    if result.endpoints_discovered:
        stdout_console.print("    [bold]Endpoints:[/bold]")
        for endpoint in result.endpoints_discovered[:5]:
            stdout_console.print(f"      - [cyan]{endpoint.url}[/cyan] ({endpoint.type})")
        remaining = len(result.endpoints_discovered) - 5
        if remaining > 0:
            stdout_console.print(f"      [dim]+ {remaining} more[/dim]")

    if result.recommended_backdoor:
        bd = result.recommended_backdoor
        if bd.status == "available":
            stdout_console.print(
                f"    [bold green]Sanctioned path[/bold green] "
                f"[dim]({bd.source_name}; registry {bd.registry_version}"
                + (
                    "; promoted from limitations"
                    if bd.promoted_from == "limitations_cross_reference"
                    else ""
                )
                + "):[/dim]"
            )
            for ep in bd.endpoints:
                auth_label = f", auth: {ep.auth}" if ep.auth else ""
                stdout_console.print(
                    f"      - [green]{ep.url}[/green] [dim]({ep.type}{auth_label})[/dim]"
                )
            for req_key, req_val in bd.requires.items():
                stdout_console.print(f"      [yellow]requires {req_key}:[/yellow] [dim]{req_val}[/dim]")
        else:
            stdout_console.print(
                f"    [yellow]No sanctioned automated path is known for "
                f"{bd.source_name}[/yellow] [dim](registry {bd.registry_version}): "
                f"{bd.notes or 'browser/manual access only.'}[/dim]"
            )

    if result.low_confidence_warning:
        stdout_console.print(
            "    [yellow]Warning:[/yellow] confidence is below threshold; review limitations."
        )

    if result.limitations:
        stdout_console.print("    [yellow]Limitations:[/yellow]")
        for lim in result.limitations:
            stdout_console.print(f"      - [yellow]{lim}[/yellow]")

    if verbose and result.unverified_candidates:
        stdout_console.print("    [magenta]Unverified candidates[/magenta] [dim](quarantined, not deleted; inspect before discarding):[/dim]")
        for cand in result.unverified_candidates:
            stdout_console.print(
                f"      - [magenta]{cand.value}[/magenta] [dim](from {cand.source}; {cand.reason})[/dim]"
            )
    elif verbose and result.hallucinations_stripped:
        stdout_console.print("    [magenta]Hallucinations stripped:[/magenta]")
        for url in result.hallucinations_stripped:
            stdout_console.print(f"      - [magenta]{url}[/magenta]")

    if verbose:
        stdout_console.print()
        stdout_console.print(f"    [dim]model: {result.model}[/dim]")
        stdout_console.print(
            f"    [dim]stages: completed {result.probe_stages_completed} | "
            f"skipped {result.probe_stages_skipped} ({result.skip_reason})[/dim]"
        )
        stdout_console.print(
            f"    [dim]probe_timestamp: {result.probe_timestamp.isoformat()}[/dim]"
        )


def _print_json(result: ProbeResult) -> None:
    """Dump the full probe result as indented JSON to stdout."""
    payload = result.model_dump(mode="json")
    json_module.dump(payload, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


@app.command()
def main(
    url: str = typer.Argument(..., help="URL to probe."),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the full ProbeResult as JSON instead of rich text."
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Include model + stage trace in rich output."
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Refuse to recommend a strategy when confidence is below "
        "the threshold.",
    ),
    debug: bool = typer.Option(
        False, "--debug", help="Route cartograph DEBUG logs to stderr."
    ),
    model: str = typer.Option(
        DEFAULT_MODEL,
        "--model",
        help="Override the pinned Claude model (default: claude-sonnet-4-6).",
    ),
    timeout: float = typer.Option(
        10.0, "--timeout", help="Per-request timeout in seconds."
    ),
    contact_email: str = typer.Option(
        None,
        "--contact-email",
        envvar="CARTOGRAPH_CONTACT_EMAIL",
        help="Operator contact email, declared in the User-Agent on hosts "
        "that ask for it (SEC convention).",
    ),
    no_preflight: bool = typer.Option(
        False,
        "--no-preflight",
        help="Skip the Anthropic key preflight check (one ~$0.00001 "
        "API ping before any probe traffic).",
    ),
    show_version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the cartograph-ai version and exit.",
    ),
) -> None:
    """Probe a URL and emit a classification.

    Example:

        cartograph-ai https://www.nhtsa.gov/recalls
    """
    _configure_logging(debug=debug)

    try:
        result = probe(
            url,
            options=ProbeOptions(
                strict=strict,
                debug=debug,
                model=model,
                timeout=timeout,
                preflight_key_check=not no_preflight,
                contact_email=contact_email,
            ),
        )
    except CartographError as exc:
        stderr_console.print(f"[red]cartograph error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except Exception as exc:  # pragma: no cover - unexpected
        stderr_console.print(f"[red]Unexpected error:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(code=2) from exc

    if json_output:
        _print_json(result)
    else:
        _print_rich(result, verbose=verbose)


if __name__ == "__main__":  # pragma: no cover
    app()
