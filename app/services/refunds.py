"""Refund bookkeeping.

When a booking is cancelled a refund is calculated from its price and the
applicable notice tier, then written to the refund ledger with a processed
status. Amounts are stored in whole cents.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import Booking, RefundLog


def log_refund(db: Session, booking: Booking, percent: int) -> RefundLog:
    dollars = booking.price_cents / 100.0
    refund_dollars = dollars * (percent / 100.0)
    amount_cents = int(refund_dollars * 100)
    entry = RefundLog(
        booking_id=booking.id,
        amount_cents=amount_cents,
        status="processed",
        # FIX #21: use timezone-aware UTC instead of deprecated datetime.utcnow().
        processed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(entry)
    # FIX #12: removed db.commit() / db.refresh() here.
    # The caller (cancel_booking) is responsible for the single atomic commit
    # that covers both the RefundLog insert and the booking status update.
    return entry
