from app.db import SessionLocal
from app.models import Card, Source

SOURCES = [
    {"name": "yuyutei", "base_url": "https://yuyu-tei.jp"},
    {"name": "snkrdunk", "base_url": "https://snkrdunk.com"},
]

CARDS = [
    {"card_code": "OP01-001", "name_en": "Monkey D. Luffy", "name_jp": "モンキー・D・ルフィ", "set_code": "OP01", "rarity": "L", "variant": "base", "language": "jp"},
    {"card_code": "OP01-013", "name_en": "Roronoa Zoro", "name_jp": "ロロノア・ゾロ", "set_code": "OP01", "rarity": "SR", "variant": "base", "language": "jp"},
    {"card_code": "OP01-024", "name_en": "Nami", "name_jp": "ナミ", "set_code": "OP01", "rarity": "R", "variant": "base", "language": "jp"},
    {"card_code": "OP01-034", "name_en": "Usopp", "name_jp": "ウソップ", "set_code": "OP01", "rarity": "R", "variant": "base", "language": "jp"},
    {"card_code": "OP01-041", "name_en": "Sanji", "name_jp": "サンジ", "set_code": "OP01", "rarity": "R", "variant": "base", "language": "jp"},
    {"card_code": "OP02-013", "name_en": "Trafalgar Law", "name_jp": "トラファルガー・ロー", "set_code": "OP02", "rarity": "SR", "variant": "base", "language": "jp"},
    {"card_code": "OP02-025", "name_en": "Nico Robin", "name_jp": "ニコ・ロビン", "set_code": "OP02", "rarity": "R", "variant": "base", "language": "jp"},
    {"card_code": "OP03-013", "name_en": "Yamato", "name_jp": "ヤマト", "set_code": "OP03", "rarity": "SR", "variant": "base", "language": "jp"},
    {"card_code": "OP04-004", "name_en": "Shanks", "name_jp": "シャンクス", "set_code": "OP04", "rarity": "SEC", "variant": "base", "language": "jp"},
    {"card_code": "OP05-119", "name_en": "Kaido", "name_jp": "カイドウ", "set_code": "OP05", "rarity": "SEC", "variant": "alt_art", "language": "jp"},
]


def seed() -> None:
    db = SessionLocal()
    try:
        for source_data in SOURCES:
            exists = db.query(Source).filter_by(name=source_data["name"]).one_or_none()
            if exists is None:
                db.add(Source(**source_data))

        for card_data in CARDS:
            exists = (
                db.query(Card)
                .filter_by(
                    card_code=card_data["card_code"],
                    set_code=card_data["set_code"],
                    rarity=card_data["rarity"],
                    variant=card_data["variant"],
                    language=card_data["language"],
                )
                .one_or_none()
            )
            if exists is None:
                db.add(Card(**card_data))

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
