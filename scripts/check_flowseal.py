"""Check a local Flowseal corpus without executing its batch files or using a router.

Run: python -m scripts.check_flowseal SOURCE [--json REPORT.json]
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from zapret_keenetic.converter import ConverterSettings, convert
from zapret_keenetic.gui import discover_profiles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    names = discover_profiles(args.source)
    if not names:
        parser.error("no winws profiles found")
    results = []
    for name in names:
        for target in ("keenetic", "openwrt"):
            for game in ("disabled", "all", "tcp", "udp"):
                for tls_mode, limit in (("source", None), ("clone", 3)):
                    with tempfile.TemporaryDirectory() as temporary:
                        result = convert(ConverterSettings(
                            source=args.source, profile=name, output=Path(temporary),
                            target=target, game_filter=game, strict=True,
                            tls_fake_mode=tls_mode, fake_repeats_limit=limit,
                        ))
                        results.append({"profile": name, "target": target, "game_filter": game,
                                        "tls_fake_mode": tls_mode, "fake_repeats_limit": limit,
                                        "profiles_written": result.profiles_written,
                                        "warnings": result.warning_count})
    report = {"source_profiles": len(names), "conversions_passed": len(results), "results": results}
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Passed {len(results)} strict conversions from {len(names)} source profiles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
