"""Shared report printers for OPC UA bottleneck diagnostics."""

from __future__ import annotations

from typing import Any


def print_multi_table_header() -> None:
    """Print compact multi-server table header."""
    print(
        f"  {'mode':>4} "
        f"{'sched':>5} "
        f"{'srv':>3} "
        f"{'hz':>6} "
        f"{'vars':>10} "
        f"{'reads':>7} "
        f"{'bad_cnt':>7} "
        f"{'min_resp_p':>10} "
        f"{'resp_j95':>9} "
        f"{'resp_jmax':>10} "
        f"{'r95':>7} "
        f"{'rmax':>7} "
        f"{'t95':>7} "
        f"{'tmax':>7} "
        f"{'cpu':>6} "
        f"{'status':>7}"
    )


def print_multi_level_result(result: Any) -> None:
    """Print one multi-server hz level row."""
    status = "PASS" if result.passed else "FAIL"
    vars_text = f"{result.vars_per_server}/{result.total_variable_count}"

    print(
        f"  {result.reader_mode[:4]:>4} "
        f"{result.read_schedule[:5]:>5} "
        f"{result.server_count:>3} "
        f"{result.target_hz:>6.1f} "
        f"{vars_text:>10} "
        f"{result.ok_reads:>7} "
        f"{result.batch_mismatches:>7} "
        f"{result.min_response_period_pass_ratio:>10.3f} "
        f"{result.response_period_jitter_p95_ms:>9.1f} "
        f"{result.response_period_jitter_max_ms:>10.1f} "
        f"{result.read_p95_ms:>7.1f} "
        f"{result.read_max_ms:>7.1f} "
        f"{result.tick_p95_ms:>7.1f} "
        f"{result.tick_max_ms:>7.1f} "
        f"{result.cpu_mean_percent:>6.1f} "
        f"{status:>7}"
    )

    if result.failure_reason:
        print(f"       failure_reason: {result.failure_reason}")


def print_multi_summary(result: Any, *, config: dict[str, Any]) -> None:
    """Print full multi-server summary with context and max-pass table."""
    print()
    print("=" * 140)
    print("  source_simulation multi server OPC UA 最大可用频率诊断结果")
    print("=" * 140)
    for key, value in config.items():
        print(f"  {key}={value}")
    print()

    print_multi_table_header()
    for ramp in result.ramps:
        for level in ramp.levels:
            print_multi_level_result(level)

    print()
    print("  max pass by server_count:")
    print(
        f"  {'srv':>3} "
        f"{'max_hz':>8} "
        f"{'vars':>10} "
        f"{'values/s':>12} "
        f"{'reads':>8} "
        f"{'min_resp_p':>10} "
        f"{'resp_j95':>9} "
        f"{'resp_jmax':>10} "
        f"{'r95':>7} "
        f"{'rmax':>7} "
        f"{'t95':>7} "
        f"{'tmax':>7} "
        f"{'cpu':>6}"
    )

    for ramp in result.ramps:
        pass_levels = [level for level in ramp.levels if level.passed]
        if not pass_levels:
            print(f"  {ramp.server_count:>3} {'N/A':>8}")
            continue

        best = pass_levels[-1]
        vars_text = f"{best.vars_per_server}/{best.total_variable_count}"
        print(
            f"  {best.server_count:>3} "
            f"{best.target_hz:>8.1f} "
            f"{vars_text:>10} "
            f"{best.values_per_second:>12.0f} "
            f"{best.ok_reads:>8} "
            f"{best.min_response_period_pass_ratio:>10.3f} "
            f"{best.response_period_jitter_p95_ms:>9.1f} "
            f"{best.response_period_jitter_max_ms:>10.1f} "
            f"{best.read_p95_ms:>7.1f} "
            f"{best.read_max_ms:>7.1f} "
            f"{best.tick_p95_ms:>7.1f} "
            f"{best.tick_max_ms:>7.1f} "
            f"{best.cpu_mean_percent:>6.1f}"
        )

    print("=" * 140)
    print()


def print_single_level_result(result: Any) -> None:
    """Print one single-server hz level diagnostic block."""
    status = "PASS" if result.passed else "FAIL"

    print()
    print(f"[hz={result.target_hz:.1f} | period={result.target_period_ms:.1f}ms | {status}]")
    print(
        "  ticks: "
        f"exp={result.expected_ticks}, "
        f"done={result.completed_ticks}, "
        f"failed={result.failed_ticks}, "
        f"miss={result.missed_ticks}, "
        f"miss_ratio={result.missed_ratio:.3f}, "
        f"ach={result.achieved_ratio:.3f}, "
        f"ach_hz={result.achieved_hz:.2f}"
    )
    print(
        "  read_ms: "
        f"mean={result.read_mean_ms:.1f}, "
        f"p50={result.read_p50_ms:.1f}, "
        f"p95={result.read_p95_ms:.1f}, "
        f"p99={result.read_p99_ms:.1f}, "
        f"max={result.read_max_ms:.1f}, "
        f"spikes={result.read_spike_count}"
    )
    print(
        "  post_ms: "
        f"mean={result.post_mean_ms:.3f}, "
        f"p50={result.post_p50_ms:.3f}, "
        f"p95={result.post_p95_ms:.3f}, "
        f"p99={result.post_p99_ms:.3f}, "
        f"max={result.post_max_ms:.3f}, "
        f"spikes={result.post_spike_count}"
    )
    print(
        "  tick_ms: "
        f"mean={result.tick_mean_ms:.1f}, "
        f"p50={result.tick_p50_ms:.1f}, "
        f"p95={result.tick_p95_ms:.1f}, "
        f"p99={result.tick_p99_ms:.1f}, "
        f"max={result.tick_max_ms:.1f}, "
        f"spikes={result.tick_spike_count}"
    )
    print(
        "  client_period: "
        f"samples={result.client_period_samples}, "
        f"pass={result.client_period_pass_ratio:.3f}, "
        f"p95err={result.client_period_p95_error_ms:.1f}ms, "
        f"p99err={result.client_period_p99_error_ms:.1f}ms"
    )
    print(
        "  response_ts: "
        f"count={result.response_timestamp_count}, "
        f"observed_hz={result.response_timestamp_observed_hz:.2f}, "
        f"p95err={result.response_timestamp_period_p95_error_ms:.1f}ms"
    )
    print(
        "  errors: "
        f"mismatch={result.batch_mismatches}, "
        f"read_errors={result.read_errors}, "
        f"cpu_mean={result.cpu_mean_percent:.1f}%, "
        f"cpu_peak={result.cpu_peak_percent:.1f}%"
    )

    if result.failure_reason:
        print(f"  failure_reason: {result.failure_reason}")


def print_single_summary(ramp_result: Any, *, config: dict[str, Any]) -> None:
    """Print full single-server summary and legend."""
    print()
    print("=" * 132)
    print("  source_simulation 单 server OPC UA 最大可用频率诊断结果")
    print("=" * 132)
    for key, value in config.items():
        print(f"  {key}={value}")
    print()

    max_pass = f"{ramp_result.max_pass_hz:.1f}Hz" if ramp_result.max_pass_hz is not None else "N/A"
    print(f"  max_pass_hz={max_pass}")
    print()

    header = (
        f"  {'hz':>6} "
        f"{'period':>8} "
        f"{'done':>6} "
        f"{'miss%':>7} "
        f"{'ach':>6} "
        f"{'r95':>7} "
        f"{'r99':>7} "
        f"{'rmax':>7} "
        f"{'rspk':>5} "
        f"{'p95':>7} "
        f"{'p99':>7} "
        f"{'t95':>7} "
        f"{'t99':>7} "
        f"{'tmax':>7} "
        f"{'tspk':>5} "
        f"{'cli_p':>6} "
        f"{'cli99':>7} "
        f"{'cpu':>6} "
        f"{'status':>7}"
    )
    print(header)

    for level in ramp_result.levels:
        status = "PASS" if level.passed else "FAIL"
        print(
            f"  {level.target_hz:>6.1f} "
            f"{level.target_period_ms:>8.1f} "
            f"{level.completed_ticks:>6} "
            f"{level.missed_ratio * 100:>7.2f} "
            f"{level.achieved_ratio:>6.3f} "
            f"{level.read_p95_ms:>7.1f} "
            f"{level.read_p99_ms:>7.1f} "
            f"{level.read_max_ms:>7.1f} "
            f"{level.read_spike_count:>5} "
            f"{level.post_p95_ms:>7.3f} "
            f"{level.post_p99_ms:>7.3f} "
            f"{level.tick_p95_ms:>7.1f} "
            f"{level.tick_p99_ms:>7.1f} "
            f"{level.tick_max_ms:>7.1f} "
            f"{level.tick_spike_count:>5} "
            f"{level.client_period_pass_ratio:>6.3f} "
            f"{level.client_period_p99_error_ms:>7.1f} "
            f"{level.cpu_mean_percent:>6.1f} "
            f"{status:>7}"
        )

    print("=" * 132)
    print()
