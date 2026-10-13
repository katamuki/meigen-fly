"""Correct author descriptions that were imported with mistakes.

Runs after verify_migration.py in rebuild_sqlite.sh, so the row-by-row check
against the dump still sees the original data. Each fix names the exact text
it expects; if the source was edited since, nothing is changed and the script
stops so the fix can be reviewed (docs/database/migration-runbook.md §5).

- Stray foreign words or research notes left in the text are removed.
- Descriptions that may describe a different person with the same name are
  cleared (NULL), so the site never shows a possibly wrong biography.

Usage: uv run python scripts/fix_author_descriptions.py --database PATH
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import Engine, text

from app.db import create_db_engine
from app.instants import format_instant

# author id -> (description expected in the dump, corrected description)
FIXES: dict[int, tuple[str, str | None]] = {
    # ジャン・ド・ラ・ブリュイエール
    1123: (
        "17世紀フランスのモラリスト文学者。古代ギリシャのテオプラストスの著作『人さまざま』に独自の人間観察を加えた『カラクテール』の著者として知られる。同時代の人々を類型化し、その性格や振る舞いを辛辣かつ остроумно (witfully) に描き出した。その作品は、人間性の普遍的な探求として今日でも高く評価されている。",
        "17世紀フランスのモラリスト文学者。古代ギリシャのテオプラストスの著作『人さまざま』に独自の人間観察を加えた『カラクテール』の著者として知られる。同時代の人々を類型化し、その性格や振る舞いを辛辣かつ機知に富んだ筆致で描き出した。その作品は、人間性の普遍的な探求として今日でも高く評価されている。",
    ),
    # エレン・スー・スターン
    1193: (
        "アメリカの作家、コンサルタント。Expecting Change Workshopsの創設者。人間関係や自己啓発に関する多数の著作があり、その多くがベストセラーとなっている。※調査しましたが、詳細な情報を特定できませんでした。",
        "アメリカの作家、コンサルタント。Expecting Change Workshopsの創設者。人間関係や自己啓発に関する多数の著作があり、その多くがベストセラーとなっている。",
    ),
    # 伊藤 聖
    1206: (
        "※調査しましたが、詳細な情報を特定できませんでした。同姓同名の著名人が複数存在するため、名言の主と異なる可能性があります。",
        None,
    ),
    # 奥 紳平
    1222: (
        "※同名の著名人が複数存在し、人物を特定できませんでした。",
        None,
    ),
    # アーネスト・ハスキンズ
    1364: (
        "※調査しましたが、詳細な情報を特定できませんでした。",
        None,
    ),
    # 関口 峭市
    1382: (
        "※調査しましたが、詳細な情報を特定できませんでした。",
        None,
    ),
    # モーリス・ブデル
    1390: (
        "※調査しましたが、詳細な情報を特定できませんでした。",
        None,
    ),
    # ジョージ・T・ヒューイット
    1403: (
        "※調査しましたが、詳細な情報を特定できませんでした。",
        None,
    ),
    # アンドレ・プレヴォ
    1105: (
        "フランスの男子テニス選手。1900年の全仏選手権（現在の全仏オープン）で男子シングルス準優勝、同年のパリオリンピックで男子ダブルスの銅メダルを獲得した。※同姓同名の著名人が複数存在するため、名言の主と異なる可能性があります。",
        None,
    ),
    # ジェームズ・クルーク
    1256: (
        "スコットランド生まれのカナダの実業家、政治家。製紙工場を設立するなど、アッパー・カナダの産業発展に貢献した。※同姓同名の著名人が複数存在するため、名言の主と異なる可能性があります。",
        None,
    ),
    # ルー・オースティン
    1352: (
        "アメリカ合衆国のジャーナリスト、新聞発行者、公民権活動家。※同姓同名の著名人が複数存在するため、名言の主と異なる可能性があります。",
        None,
    ),
    # ロバート・ジョンソン
    1408: (
        "アメリカの伝説的なブルースミュージシャン。「キング・オブ・デルタ・ブルース」と称され、その卓越したギターテクニックと歌唱スタイルは、後の多くのロックミュージシャンに絶大な影響を与えた。27歳という若さで亡くなり、その生涯は多くの謎に包まれている。※同姓同名の著名人が複数存在するため、名言の主と異なる可能性があります。",
        None,
    ),
    # グレース・ハンセン
    1626: (
        "アメリカの作家。主に児童向けのノンフィクション作品を執筆している。※同姓同名の著名人が複数存在するため、名言の主と異なる可能性があります。",
        None,
    ),
    # 伊藤 守
    1631: (
        "日本の実業家、コーチ。株式会社毎日コムネットの創業者。日本におけるビジネスコーチングの草分け的存在であり、国際コーチ連盟から日本人初のマスター認定コーチとして認められた。※同姓同名の著名人が複数存在するため、名言の主と異なる可能性があります。",
        None,
    ),
    # E.S.スターン
    2122: (
        "アメリカの市民活動家、実業家。ニューオーリンズの市民、人種、ビジネス、政府関連の分野で指導的役割を果たした。※同姓同名の著名人が複数存在するため、名言の主と異なる可能性があります。",
        None,
    ),
    # ジョン・ヘンリー・テイラー
    2128: (
        "イギリスのプロゴルファー。19世紀末から20世紀初頭にかけて活躍し、全英オープンで5勝を挙げた「ゴルフの三巨人」の一人。※CSVの外国語名がArthur Pennとなっていますが、検索結果からJohn Henry Taylorはゴルファーであり、Arthur Pennは映画監督であるため、名言の主と異なる可能性があります。",
        None,
    ),
    # ウィリアム・ウォード
    2144: (
        "イギリスの著名な版画家（メゾティント彫刻家）。同名の人物が複数存在するため、名言の主と異なる可能性があります。",
        None,
    ),
}


class FixError(Exception):
    pass


def apply_fixes(engine: Engine) -> int:
    updated_at = format_instant(datetime.now(UTC))
    with engine.begin() as connection:
        for author_id, (expected, corrected) in FIXES.items():
            current = connection.execute(
                text("SELECT description FROM authors WHERE id = :id"),
                {"id": author_id},
            ).one_or_none()
            if current is None or current[0] != expected:
                raise FixError(f"author {author_id}: description differs from expected")
            connection.execute(
                text(
                    "UPDATE authors SET description = :description,"
                    " updated_at = :updated_at WHERE id = :id"
                ),
                {"description": corrected, "updated_at": updated_at, "id": author_id},
            )
    return len(FIXES)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()

    engine = create_db_engine(f"sqlite:///{args.database}")
    try:
        count = apply_fixes(engine)
    except FixError as error:
        sys.exit(f"fix aborted (nothing changed): {error}")
    finally:
        engine.dispose()
    print(f"{count:8d}  author descriptions fixed")


if __name__ == "__main__":
    main()
