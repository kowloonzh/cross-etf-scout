from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "cross_etf_scout.sqlite"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data"
DEFAULT_SYMBOL = "SH513310"


@dataclass(frozen=True)
class PremiumPoint:
    trade_date: str
    premium_rate: float


@dataclass(frozen=True)
class PremiumSeries:
    symbol: str
    name: str
    requested_start: str
    latest_date: str
    points: tuple[PremiumPoint, ...]


def load_latest_month_premium(
    db_path: str | Path,
    symbol: str = DEFAULT_SYMBOL,
) -> PremiumSeries:
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"数据库不存在：{path}")

    database_uri = f"file:{path.resolve()}?mode=ro"
    with sqlite3.connect(database_uri, uri=True) as conn:
        latest_row = conn.execute(
            """
            select trade_date, name
            from daily_quotes
            where symbol = ?
            order by trade_date desc
            limit 1
            """,
            (symbol,),
        ).fetchone()
        if latest_row is None:
            raise ValueError(f"数据库中没有标的 {symbol} 的数据")

        latest_date, name = latest_row
        requested_start = conn.execute(
            "select date(?, '-1 month')", (latest_date,)
        ).fetchone()[0]
        rows = conn.execute(
            """
            select trade_date, premium_rate
            from daily_quotes
            where symbol = ?
              and trade_date between ? and ?
            order by trade_date
            """,
            (symbol, requested_start, latest_date),
        ).fetchall()

    if not rows:
        raise ValueError(f"标的 {symbol} 在最近一个月没有数据")
    null_dates = [trade_date for trade_date, value in rows if value is None]
    if null_dates:
        raise ValueError("最近一个月存在空溢价率：" + ", ".join(null_dates))

    points = tuple(PremiumPoint(date, float(value)) for date, value in rows)
    dates = [point.trade_date for point in points]
    if len(dates) != len(set(dates)):
        raise ValueError("最近一个月存在重复交易日期")

    return PremiumSeries(
        symbol=symbol,
        name=name,
        requested_start=requested_start,
        latest_date=latest_date,
        points=points,
    )


def render_echarts_option(series: PremiumSeries) -> str:
    first_data_date = series.points[0].trade_date
    dates = ",\n".join(f"      '{point.trade_date}'" for point in series.points)
    values = ",\n".join(
        f"        {point.premium_rate:.2f}" for point in series.points
    )

    return f"""// 数据源：data/cross_etf_scout.sqlite / daily_quotes
// 标的：{series.symbol} {series.name}
// 查询区间：{series.requested_start} 至 {series.latest_date}
// 实际数据：{first_data_date} 至 {series.latest_date}，共 {len(series.points)} 个交易日
// 数值单位：%
option = {{
  title: {{
    text: '中韩半导体ETF近一个月溢价率',
    subtext: '{series.symbol} | {first_data_date} 至 {series.latest_date}'
  }},
  tooltip: {{
    trigger: 'axis',
    valueFormatter: function (value) {{
      return Number(value).toFixed(2) + '%';
    }}
  }},
  grid: {{
    left: 60,
    right: 32,
    top: 85,
    bottom: 60
  }},
  xAxis: {{
    type: 'category',
    boundaryGap: false,
    name: '日期',
    data: [
{dates}
    ],
    axisLabel: {{
      rotate: 45
    }}
  }},
  yAxis: {{
    type: 'value',
    name: '溢价率（%）',
    scale: true,
    axisLabel: {{
      formatter: '{{value}}%'
    }},
    splitLine: {{
      lineStyle: {{
        type: 'dashed'
      }}
    }}
  }},
  series: [
    {{
      name: '溢价率',
      type: 'line',
      smooth: true,
      showSymbol: true,
      symbol: 'circle',
      symbolSize: 7,
      data: [
{values}
      ],
      lineStyle: {{
        width: 3,
        color: '#5470c6'
      }},
      itemStyle: {{
        color: '#5470c6'
      }},
      areaStyle: {{
        color: {{
          type: 'linear',
          x: 0,
          y: 0,
          x2: 0,
          y2: 1,
          colorStops: [
            {{ offset: 0, color: 'rgba(84, 112, 198, 0.35)' }},
            {{ offset: 1, color: 'rgba(84, 112, 198, 0.03)' }}
          ]
        }}
      }},
      markPoint: {{
        data: [
          {{ type: 'max', name: '最高' }},
          {{ type: 'min', name: '最低' }}
        ]
      }},
      markLine: {{
        symbol: 'none',
        data: [
          {{ type: 'average', name: '平均值' }}
        ]
      }}
    }}
  ]
}};
"""


def generate_premium_echarts(
    db_path: str | Path = DEFAULT_DB_PATH,
    symbol: str = DEFAULT_SYMBOL,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> Path:
    series = load_latest_month_premium(db_path, symbol)
    output_path = Path(output_dir) / (
        "zhonghan_semiconductor_premium_"
        f"{series.requested_start.replace('-', '')}_"
        f"{series.latest_date.replace('-', '')}.js"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_echarts_option(series), encoding="utf-8")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从本地 SQLite 生成中韩半导体最近一个月溢价率 ECharts 文件。"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--upload",
        action="store_true",
        help="生成后调用 v2github 上传。",
    )
    parser.add_argument(
        "--target-path",
        help="传给 v2github 的可选远端相对路径；仅与 --upload 一起使用。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.target_path and not args.upload:
        raise SystemExit("--target-path 只能与 --upload 一起使用")

    output_path = generate_premium_echarts(args.db, args.symbol, args.output_dir)
    print(f"已生成：{output_path}")

    if args.upload:
        uploader = shutil.which("v2github")
        if uploader is None:
            raise SystemExit("找不到 v2github，请确认它已安装到 PATH")
        command = [uploader, str(output_path)]
        if args.target_path:
            command.append(args.target_path)
        subprocess.run(command, check=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
