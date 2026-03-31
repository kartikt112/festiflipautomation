"""Seed the database with realistic Dutch festival ticket data."""

import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    from app.database import async_session
    from app.models.sell_offer import SellOffer, OfferStatus
    from app.models.buy_request import BuyRequest, BuyStatus
    from app.models.reservation import Reservation, ReservationStatus
    from app.models.payment import Payment, PaymentStatus
    from app.models.user import User
    from decimal import Decimal
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)

    async with async_session() as db:
        # ── SELLERS ──
        sellers = [
            SellOffer(
                first_name="Jan", last_name="de Vries", phone="+31612345001",
                email="jan@example.nl", instagram="@jan_dv", gender="M",
                city="Amsterdam", postcode="1012AB",
                event_name="Lowlands 2025", event_date=datetime(2025, 8, 15, tzinfo=timezone.utc),
                quantity=2, price_per_ticket=Decimal("80.00"), total_price=Decimal("160.00"),
                sale_type="REGULAR", verification_status="VERIFIED",
                status=OfferStatus.AVAILABLE, agreement_accepted=True,
            ),
            SellOffer(
                first_name="Sophie", last_name="Bakker", phone="+31612345002",
                email="sophie@example.nl", instagram="@sophie_b", gender="F",
                city="Rotterdam", postcode="3011AA",
                event_name="Mysteryland 2025", event_date=datetime(2025, 8, 23, tzinfo=timezone.utc),
                quantity=4, price_per_ticket=Decimal("95.00"), total_price=Decimal("380.00"),
                sale_type="REGULAR", verification_status="VERIFIED",
                status=OfferStatus.AVAILABLE, agreement_accepted=True,
            ),
            SellOffer(
                first_name="Lucas", last_name="Jansen", phone="+31612345003",
                email="lucas@example.nl", gender="M",
                city="Utrecht", postcode="3511AB",
                event_name="Defqon.1 2025", event_date=datetime(2025, 6, 27, tzinfo=timezone.utc),
                quantity=3, price_per_ticket=Decimal("120.00"), total_price=Decimal("360.00"),
                sale_type="REGULAR", verification_status="UNVERIFIED",
                status=OfferStatus.AVAILABLE, agreement_accepted=True,
            ),
            SellOffer(
                first_name="Emma", last_name="Visser", phone="+31612345004",
                email="emma.v@example.nl", instagram="@emma_vis", gender="F",
                city="Den Haag", postcode="2511AB",
                event_name="Lowlands 2025", event_date=datetime(2025, 8, 15, tzinfo=timezone.utc),
                quantity=1, price_per_ticket=Decimal("75.00"), total_price=Decimal("75.00"),
                sale_type="REGULAR", verification_status="TRUSTED",
                status=OfferStatus.RESERVED, agreement_accepted=True,
            ),
            SellOffer(
                first_name="Daan", last_name="Mulder", phone="+31612345005",
                email="daan@example.nl", gender="M",
                city="Eindhoven", postcode="5611AB",
                event_name="Awakenings 2025", event_date=datetime(2025, 7, 12, tzinfo=timezone.utc),
                quantity=2, price_per_ticket=Decimal("65.00"), total_price=Decimal("130.00"),
                sale_type="REGULAR", verification_status="VERIFIED",
                status=OfferStatus.SOLD, agreement_accepted=True,
            ),
            SellOffer(
                first_name="Lotte", last_name="de Groot", phone="+31612345006",
                email="lotte@example.nl", instagram="@lotte_dg", gender="F",
                city="Groningen", postcode="9711AB",
                event_name="Into The Great Wide Open 2025", event_date=datetime(2025, 9, 5, tzinfo=timezone.utc),
                quantity=2, price_per_ticket=Decimal("55.00"), total_price=Decimal("110.00"),
                sale_type="REGULAR", verification_status="VERIFIED",
                status=OfferStatus.AVAILABLE, agreement_accepted=True,
            ),
        ]
        for s in sellers:
            db.add(s)
        await db.flush()

        # ── BUYERS ──
        buyers = [
            BuyRequest(
                first_name="Thomas", last_name="Smit", phone="+31698765001",
                email="thomas@example.nl", city="Amsterdam",
                event_name="Lowlands 2025", quantity=2,
                max_price_per_ticket=Decimal("90.00"),
                source="WHATSAPP", status=BuyStatus.MATCHED, agreement_accepted=True,
            ),
            BuyRequest(
                first_name="Lisa", last_name="van Dijk", phone="+31698765002",
                email="lisa@example.nl", city="Rotterdam",
                event_name="Mysteryland 2025", quantity=2,
                max_price_per_ticket=Decimal("100.00"),
                source="WHATSAPP", status=BuyStatus.WAITING, agreement_accepted=True,
            ),
            BuyRequest(
                first_name="Sem", last_name="Hendriks", phone="+31698765003",
                email="sem@example.nl", city="Utrecht",
                event_name="Defqon.1 2025", quantity=2,
                max_price_per_ticket=Decimal("130.00"),
                source="FORM", status=BuyStatus.WAITING, agreement_accepted=True,
            ),
            BuyRequest(
                first_name="Anna", last_name="Bos", phone="+31698765004",
                email="anna@example.nl", city="Leiden",
                event_name="Awakenings 2025", quantity=2,
                max_price_per_ticket=Decimal("70.00"),
                source="WHATSAPP", status=BuyStatus.MATCHED, agreement_accepted=True,
            ),
            BuyRequest(
                first_name="Milan", last_name="Peters", phone="+31698765005",
                email="milan@example.nl", city="Tilburg",
                event_name="Lowlands 2025", quantity=1,
                max_price_per_ticket=Decimal("85.00"),
                source="WHATSAPP", status=BuyStatus.WAITING, agreement_accepted=True,
            ),
        ]
        for b in buyers:
            db.add(b)
        await db.flush()

        # ── RESERVATIONS ──
        reservations = [
            # Active reservation (pending payment)
            Reservation(
                buy_request_id=buyers[0].id, sell_offer_id=sellers[3].id,
                quantity=1, deposit_amount=Decimal("5.63"),
                remaining_amount=Decimal("69.37"), minimum_applied=False,
                stripe_session_id="cs_test_pending_001",
                stripe_checkout_url="https://checkout.stripe.com/test/pending001",
                status=ReservationStatus.PENDING,
                expires_at=now + timedelta(minutes=45),
            ),
            # Completed reservation (paid)
            Reservation(
                buy_request_id=buyers[3].id, sell_offer_id=sellers[4].id,
                quantity=2, deposit_amount=Decimal("9.75"),
                remaining_amount=Decimal("120.25"), minimum_applied=False,
                stripe_session_id="cs_test_paid_001",
                stripe_checkout_url="https://checkout.stripe.com/test/paid001",
                status=ReservationStatus.PAID,
                paid_at=now - timedelta(hours=2),
                expires_at=now - timedelta(hours=1),
            ),
            # Expired reservation
            Reservation(
                buy_request_id=buyers[4].id, sell_offer_id=sellers[0].id,
                quantity=1, deposit_amount=Decimal("6.00"),
                remaining_amount=Decimal("74.00"), minimum_applied=False,
                stripe_session_id="cs_test_expired_001",
                stripe_checkout_url="https://checkout.stripe.com/test/expired001",
                status=ReservationStatus.EXPIRED,
                expires_at=now - timedelta(hours=3),
            ),
        ]
        for r in reservations:
            db.add(r)
        await db.flush()

        # ── PAYMENTS ──
        payments = [
            Payment(
                reservation_id=reservations[0].id,
                deposit_amount=Decimal("5.63"), minimum_applied=False,
                stripe_session_id="cs_test_pending_001",
                status=PaymentStatus.PENDING,
            ),
            Payment(
                reservation_id=reservations[1].id,
                deposit_amount=Decimal("9.75"), minimum_applied=False,
                stripe_session_id="cs_test_paid_001",
                stripe_payment_intent_id="pi_test_completed_001",
                webhook_event_id="evt_test_completed_001",
                status=PaymentStatus.COMPLETED,
            ),
        ]
        for p in payments:
            db.add(p)

        # ── USERS ──
        users = [
            User(phone="+31612345001", first_name="Jan", last_name="de Vries", role="SELLER"),
            User(phone="+31612345002", first_name="Sophie", last_name="Bakker", role="SELLER"),
            User(phone="+31698765001", first_name="Thomas", last_name="Smit", role="BUYER"),
            User(phone="+31698765002", first_name="Lisa", last_name="van Dijk", role="BUYER"),
            User(phone="+31698765004", first_name="Anna", last_name="Bos", role="BUYER"),
        ]
        for u in users:
            db.add(u)

        await db.commit()

        print("✅ Seeded database with:")
        print(f"   🎫 {len(sellers)} sell offers (3 AVAILABLE, 1 RESERVED, 1 SOLD, 1 AVAILABLE)")
        print(f"   🛒 {len(buyers)} buy requests (2 MATCHED, 3 WAITING)")
        print(f"   🔒 {len(reservations)} reservations (1 PENDING, 1 PAID, 1 EXPIRED)")
        print(f"   💰 {len(payments)} payments (1 PENDING, 1 COMPLETED)")
        print(f"   👤 {len(users)} users")
        print(f"\n   View at: http://localhost:8000/admin/")


if __name__ == "__main__":
    asyncio.run(main())
