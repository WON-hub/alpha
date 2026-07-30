from __future__ import annotations

import argparse
import random
from datetime import datetime

from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.models import Restaurant, Review


DUMMY_MARKER = "[더미 리뷰]"
NAMES = [
    "김민준", "이서연", "박지훈", "최하은", "정도윤", "한유진", "오지호", "윤채원",
    "땅콩너굴이", "노스끼", "밥먹는참새", "광운맛탐험대", "치즈냥", "오늘도한끼", "다람쥐러버",
]
COMMENTS = {
    5: ["혜택도 이용하기 좋고 매장 분위기도 만족스러웠어요.", "재방문하고 싶은 곳이에요. 음식과 서비스가 모두 좋았습니다."],
    4: ["전체적으로 만족스러웠어요. 다음에도 이용할 것 같아요.", "메뉴가 괜찮고 제휴 혜택도 알차게 느껴졌습니다."],
    3: ["무난하게 이용하기 좋았어요. 다음에는 다른 메뉴도 먹어보려 해요.", "보통 정도로 만족했습니다. 위치는 편리했어요."],
    2: ["혜택은 확인했지만 조금 아쉬운 점이 있었어요.", "기대보다는 아쉬웠지만 이용은 가능했습니다."],
    1: ["이번 이용은 아쉬웠어요. 다음에는 개선되면 좋겠습니다.", "서비스가 기대와 달라서 아쉬움이 남았습니다."],
}


def add_dummy_reviews(*, apply: bool, seed: int) -> None:
    init_db()
    rng = random.Random(seed)
    with SessionLocal() as db:
        restaurants = db.scalars(select(Restaurant).where(Restaurant.status == "active").order_by(Restaurant.id)).all()
        if not apply:
            print(f"미리보기: 활성 매장 {len(restaurants)}곳에 매장별 3~8개 더미 리뷰를 추가합니다.")
            print("실제 반영하려면 --apply를 붙이세요.")
            return

        inserted = 0
        for restaurant in restaurants:
            existing_dummy = db.scalars(
                select(Review).where(
                    Review.restaurant_id == restaurant.id,
                    Review.content.startswith(DUMMY_MARKER),
                )
            ).all()
            target_count = rng.randint(3, 8)
            for _ in range(max(0, target_count - len(existing_dummy))):
                rating = rng.choice([2, 3, 3, 4, 4, 4, 5, 5])
                author = rng.choice(NAMES)
                content = f"{DUMMY_MARKER} {rng.choice(COMMENTS[rating])}"
                db.add(Review(restaurant_id=restaurant.id, rating=rating, content=content, author_name=author))
                inserted += 1
        db.flush()

        all_restaurants = db.scalars(select(Restaurant)).all()
        total_reviews = 0
        weighted_score = 0.0
        for restaurant in all_restaurants:
            reviews = db.scalars(
                select(Review).where(Review.restaurant_id == restaurant.id, Review.is_hidden.is_(False))
            ).all()
            restaurant.review_count = len(reviews)
            restaurant.rating_average = round(sum(review.rating for review in reviews) / len(reviews), 2) if reviews else 0
            total_reviews += restaurant.review_count
            weighted_score += (restaurant.rating_average / 5 * 100) * restaurant.review_count

        platform_mean = weighted_score / total_reviews if total_reviews else 60.0
        now = datetime.utcnow()
        for restaurant in all_restaurants:
            count = max(0, int(restaurant.review_count or 0))
            actual = (float(restaurant.rating_average or 0) / 5 * 100) if count else platform_mean
            restaurant.bayesian_satisfaction_score = (10 * platform_mean + count * actual) / (10 + count)
            restaurant.satisfaction_preprocessed_at = now
        db.commit()
        print(f"매장={len(restaurants)}곳, 신규 더미 리뷰={inserted}개, 전체 리뷰={total_reviews}개")
        print(f"플랫폼 평균 만족도={platform_mean:.2f}, 베이즈 S 전처리 완료={len(all_restaurants)}곳")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add clearly marked dummy reviews for local/demo verification.")
    parser.add_argument("--apply", action="store_true", help="write reviews to the configured database")
    parser.add_argument("--seed", type=int, default=20260730, help="random seed for reproducible reruns")
    args = parser.parse_args()
    add_dummy_reviews(apply=args.apply, seed=args.seed)
