"""コマンドラインインターフェース。"""
from __future__ import annotations

import argparse
import logging
import sys

from . import __version__
from .analysis.bias import build_bias, prompt_bias
from .analysis.engine import analyze_race
from .models import TrackBias
from .pipeline import extract_race_id, fetch_race
from .report import render
from .scraper import FetchError, NetkeibaClient

EPILOG = """\
使用例:
  # 出馬表を取得して分析(馬場傾向は自然文で指定)
  python -m keiba_ai 202605021711 --bias "内有利で前残り、時計はかなり速い"

  # レースURLをそのまま渡す
  python -m keiba_ai "https://race.netkeiba.com/race/shutuba.html?race_id=202605021711"

  # 馬場傾向を対話形式で入力する
  python -m keiba_ai 202605021711 --interactive

  # 数値で細かく指定(-1.0〜+1.0)
  python -m keiba_ai 202605021711 --bias-inner 0.6 --bias-front 0.4 --bias-speed -0.3

  # 保存済みHTMLだけで動かす(オフライン)
  python -m keiba_ai 202605021711 --offline ./html_dump

  # ネット接続なしでサンプル出力を見る
  python -m keiba_ai --sample --bias "外差し有利"

馬場傾向の3軸:
  inner : +1.0=内有利  /  -1.0=外有利
  front : +1.0=前残り  /  -1.0=差し・追込有利
  speed : +1.0=高速馬場 / -1.0=時計のかかるタフな馬場
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="keiba-ai",
        description="競馬 穴馬発見AI — netkeiba の出馬表と馬柱から、荒れる可能性と穴馬候補を算出する。",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("race", nargs="?", help="race_id または出馬表のURL")
    p.add_argument("--sample", action="store_true",
                   help="ネット接続なしでサンプルレースを分析する")
    p.add_argument("--version", action="version", version=f"keiba-ai {__version__}")

    g = p.add_argument_group("馬場傾向")
    g.add_argument("--bias", metavar="TEXT",
                   help='当日の馬場傾向を自然文で(例: "内有利で前残り、時計は速い")')
    g.add_argument("--bias-inner", type=float, metavar="-1.0〜1.0", help="内(+)／外(-)有利")
    g.add_argument("--bias-front", type=float, metavar="-1.0〜1.0", help="前残り(+)／差し有利(-)")
    g.add_argument("--bias-speed", type=float, metavar="-1.0〜1.0", help="高速(+)／時計かかる(-)")
    g.add_argument("--bias-condition", choices=["良", "稍重", "重", "不良"],
                   help="馬場状態を上書きする")
    g.add_argument("--bias-confidence", type=float, default=1.0, metavar="0.0〜1.0",
                   help="馬場傾向の確信度(既定 1.0)")
    g.add_argument("-i", "--interactive", action="store_true",
                   help="馬場傾向を対話形式で入力する")

    g = p.add_argument_group("出力")
    g.add_argument("-f", "--format", choices=["text", "markdown", "json"], default="text")
    g.add_argument("--json", dest="format", action="store_const", const="json",
                   help="--format json と同じ")
    g.add_argument("--markdown", dest="format", action="store_const", const="markdown",
                   help="--format markdown と同じ")
    g.add_argument("-o", "--output", metavar="FILE", help="結果をファイルに書き出す")
    g.add_argument("-v", "--verbose", action="count", default=0, help="ログを詳しく出す")

    g = p.add_argument_group("取得")
    g.add_argument("--max-past", type=int, default=10, help="1頭あたりの参照過去走数(既定 10)")
    g.add_argument("--no-form", action="store_true",
                   help="各馬の馬柱を取得しない(高速だが精度は大きく落ちる)")
    g.add_argument("--sleep", type=float, default=1.0,
                   help="リクエスト間ウェイト秒(既定 1.0。短縮は非推奨)")
    g.add_argument("--cache-dir", default=".cache/keiba_ai", help="HTTPキャッシュの保存先")
    g.add_argument("--no-cache", action="store_true", help="キャッシュを使わない")
    g.add_argument("--offline", metavar="DIR",
                   help="通信せず、DIR に保存済みのHTMLだけを使う")
    g.add_argument("--save-html", metavar="DIR", help="取得したHTMLを DIR に保存する")
    return p


def resolve_bias(args) -> TrackBias:
    if args.interactive:
        bias = prompt_bias()
        if args.bias_condition:
            bias.condition_override = args.bias_condition
        return bias
    return build_bias(
        text=args.bias,
        inner=args.bias_inner,
        front=args.bias_front,
        speed=args.bias_speed,
        condition=args.bias_condition,
        confidence=args.bias_confidence,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=[logging.WARNING, logging.INFO, logging.DEBUG][min(args.verbose, 2)],
        format="%(levelname)s %(name)s: %(message)s",
    )

    if not args.race and not args.sample:
        build_parser().print_help()
        print("\nエラー: race_id か URL、または --sample を指定してください。", file=sys.stderr)
        return 2

    bias = resolve_bias(args)

    try:
        if args.sample:
            from .sample_data import build_sample
            race, horses = build_sample()
            extra_warnings = ["これはサンプルデータによる出力であり、実在のレースではありません。"]
        else:
            race_id = extract_race_id(args.race)
            client = NetkeibaClient(
                cache_dir=None if args.no_cache else args.cache_dir,
                sleep=args.sleep,
                offline_dir=args.offline,
                save_dir=args.save_html,
                use_cache=not args.no_cache,
            )
            race, horses, extra_warnings = fetch_race(
                client, race_id, max_past=args.max_past, fetch_form=not args.no_form
            )
    except (FetchError, ValueError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    analysis = analyze_race(race, horses, bias)
    analysis.warnings = list(extra_warnings) + analysis.warnings
    text = render(analysis, args.format)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"書き出しました: {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
