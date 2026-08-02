from app.schemas import ReviewCreate


def test_review_can_be_submitted_with_rating_only():
    review = ReviewCreate(restaurant_id=1, rating=5)

    assert review.content == ""
