"""Badger & Dodo wholesale partner portal (student demonstration).

A small Flask app used to demonstrate the AWS tier of the cloud strategy for
Badger & Dodo, the Fermoy specialty coffee roaster. Partner cafés place
one-off or weekly standing orders; the roastery sees a combined roast plan and
can export it to Amazon S3 as a dispatch sheet. The app runs in a Docker
container on EC2 instances behind an Application Load Balancer and stores data
in Amazon RDS (MySQL). Locally it falls back to SQLite so it can be developed
and tested without AWS.
"""

import csv
import io
import os
import time
from datetime import date, datetime, timedelta, timezone
from urllib import request as urlrequest

from flask import Flask, jsonify, redirect, render_template, request, url_for
from sqlalchemy import (Boolean, Column, Date, DateTime, ForeignKey, Integer,
                        MetaData, Numeric, String, Table, create_engine, func,
                        select, text)
from sqlalchemy.exc import IntegrityError

metadata = MetaData()

products = Table(
    "products", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(80), nullable=False, unique=True),
    Column("origin", String(80), nullable=False),
    Column("price_per_kg", Numeric(8, 2), nullable=False),
)

orders = Table(
    "orders", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("partner", String(120), nullable=False),
    Column("county", String(40), nullable=False),
    Column("product_id", Integer, ForeignKey("products.id"), nullable=False),
    Column("kg", Numeric(8, 2), nullable=False),
    Column("standing", Boolean, nullable=False, default=False),
    Column("roast_date", Date, nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("served_by", String(64), nullable=False),
)

# Generic product names and illustrative prices for the demonstration only.
SEED_PRODUCTS = [
    ("House Espresso Blend", "Brazil / Colombia", 23.50),
    ("Seasonal Filter", "Ethiopia", 29.00),
    ("Single Origin Guatemala", "Guatemala", 27.50),
    ("Swiss Water Decaf", "Colombia", 27.00),
]

COUNTIES = ["Cork", "Kerry", "Limerick", "Waterford", "Tipperary", "Clare",
            "Dublin", "Galway", "Other"]


def database_url() -> str:
    """RDS MySQL when DB_HOST is set, otherwise a local SQLite file."""
    host = os.environ.get("DB_HOST")
    if host:
        user = os.environ["DB_USER"]
        password = os.environ["DB_PASSWORD"]
        name = os.environ.get("DB_NAME", "badgerdodo")
        port = os.environ.get("DB_PORT", "3306")
        return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}"
    return os.environ.get("DATABASE_URL", "sqlite:///badger_local.db")


_metadata_cache: dict = {}


def instance_metadata() -> dict:
    """Instance ID and Availability Zone via IMDSv2 (cached). 'local' off AWS."""
    if _metadata_cache:
        return _metadata_cache
    info = {"instance_id": "local", "az": "local"}
    try:
        token_req = urlrequest.Request(
            "http://169.254.169.254/latest/api/token", method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"})
        token = urlrequest.urlopen(token_req, timeout=0.5).read().decode()
        for key, path in (("instance_id", "instance-id"),
                          ("az", "placement/availability-zone")):
            req = urlrequest.Request(
                f"http://169.254.169.254/latest/meta-data/{path}",
                headers={"X-aws-ec2-metadata-token": token})
            info[key] = urlrequest.urlopen(req, timeout=0.5).read().decode()
    except Exception:  # not on EC2, or metadata unreachable
        pass
    _metadata_cache.update(info)
    return _metadata_cache


ROAST_WEEKDAYS = (1, 4)  # assumed roast days: Tuesday and Friday


def next_roast_day(today: date) -> date:
    """The next roast day strictly after today."""
    for offset in range(1, 8):
        candidate = today + timedelta(days=offset)
        if candidate.weekday() in ROAST_WEEKDAYS:
            return candidate
    return today + timedelta(days=1)


def create_app(db_url: str | None = None) -> Flask:
    app = Flask(__name__)
    engine = create_engine(db_url or database_url(), pool_pre_ping=True,
                           pool_recycle=280)
    app.config["ENGINE"] = engine

    # RDS can take a moment to accept connections after the instance boots.
    for attempt in range(10):
        try:
            metadata.create_all(engine)
            break
        except Exception:
            if attempt == 9:
                raise
            time.sleep(6)

    # Several workers on several instances start at once; the unique product
    # name means only one of them succeeds in seeding and the rest move on.
    try:
        with engine.begin() as conn:
            if conn.execute(select(func.count()).select_from(products)).scalar() == 0:
                conn.execute(products.insert(), [
                    {"name": n, "origin": o, "price_per_kg": p}
                    for n, o, p in SEED_PRODUCTS])
    except IntegrityError:
        pass

    def roast_plan(conn):
        """Upcoming roast batches. Standing orders repeat on the next roast day."""
        upcoming = next_roast_day(date.today())
        one_off = (select(orders.c.roast_date, products.c.name,
                          func.sum(orders.c.kg).label("kg"),
                          func.count(orders.c.id).label("orders"))
                   .join(products, products.c.id == orders.c.product_id)
                   .where(orders.c.roast_date >= date.today())
                   .where(orders.c.standing.is_(False))
                   .group_by(orders.c.roast_date, products.c.name))
        standing = (select(products.c.name,
                           func.sum(orders.c.kg).label("kg"),
                           func.count(orders.c.id).label("orders"))
                    .join(products, products.c.id == orders.c.product_id)
                    .where(orders.c.standing.is_(True))
                    .group_by(products.c.name))
        plan: dict = {}
        for r in conn.execute(one_off):
            plan[(r.roast_date, r.name)] = [float(r.kg), r.orders]
        for r in conn.execute(standing):
            row = plan.setdefault((upcoming, r.name), [0.0, 0])
            row[0] += float(r.kg)
            row[1] += r.orders
        return [{"roast_date": d, "name": n, "kg": v[0], "orders": v[1]}
                for (d, n), v in sorted(plan.items())]

    @app.get("/")
    def index():
        with engine.connect() as conn:
            prods = [dict(r._mapping) for r in conn.execute(
                select(products).order_by(products.c.id))]
            recent = [dict(r._mapping) for r in conn.execute(
                select(orders.c.id, orders.c.partner, orders.c.county,
                       products.c.name, orders.c.kg, orders.c.standing,
                       orders.c.roast_date, orders.c.served_by)
                .join(products, products.c.id == orders.c.product_id)
                .order_by(orders.c.id.desc()).limit(10))]
            plan = roast_plan(conn)
        return render_template(
            "index.html", products=prods, recent=recent, plan=plan,
            counties=COUNTIES, meta=instance_metadata(),
            roast_day=next_roast_day(date.today()),
            bucket=os.environ.get("S3_BUCKET"),
            message=request.args.get("message"))

    @app.post("/orders")
    def create_order():
        partner = (request.form.get("partner") or "").strip()[:120]
        county = request.form.get("county", "")
        standing = request.form.get("standing") == "on"
        try:
            product_id = int(request.form["product_id"])
            kg = round(float(request.form["kg"]), 2)
        except (KeyError, ValueError):
            return redirect(url_for("index", message="Invalid order"))
        if not partner or not 0 < kg <= 500:
            return redirect(url_for("index", message="Enter a partner café and 0.25-500 kg"))
        if county not in COUNTIES:
            return redirect(url_for("index", message="Choose a delivery county"))
        with engine.begin() as conn:
            if conn.execute(select(products.c.id).where(
                    products.c.id == product_id)).first() is None:
                return redirect(url_for("index", message="Unknown coffee"))
            conn.execute(orders.insert().values(
                partner=partner, county=county, product_id=product_id, kg=kg,
                standing=standing, roast_date=next_roast_day(date.today()),
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                served_by=instance_metadata()["instance_id"]))
        kind = "Standing order" if standing else "Order"
        return redirect(url_for("index", message=f"{kind} saved for {partner}"))

    @app.get("/api/orders")
    def api_orders():
        with engine.connect() as conn:
            rows = conn.execute(
                select(orders.c.id, orders.c.partner, orders.c.county,
                       products.c.name.label("coffee"), orders.c.kg,
                       orders.c.standing, orders.c.roast_date,
                       orders.c.served_by)
                .join(products, products.c.id == orders.c.product_id)
                .order_by(orders.c.id.desc()).limit(100))
            return jsonify([{**dict(r._mapping), "kg": float(r.kg),
                             "standing": bool(r.standing),
                             "roast_date": r.roast_date.isoformat()} for r in rows])

    @app.post("/roast-plan/export")
    def export_plan():
        bucket = os.environ.get("S3_BUCKET")
        if not bucket:
            return redirect(url_for("index", message="S3_BUCKET not configured"))
        with engine.connect() as conn:
            plan = roast_plan(conn)
            dispatch = conn.execute(
                select(orders.c.county, func.sum(orders.c.kg).label("kg"),
                       func.count(orders.c.id).label("orders"))
                .where((orders.c.roast_date >= date.today()) | orders.c.standing.is_(True))
                .group_by(orders.c.county).order_by(orders.c.county)).all()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["roast_date", "coffee", "kg", "orders"])
        for row in plan:
            writer.writerow([row["roast_date"], row["name"], row["kg"], row["orders"]])
        writer.writerow([])
        writer.writerow(["dispatch_county", "kg", "orders"])
        for row in dispatch:
            writer.writerow([row.county, float(row.kg), row.orders])
        key = f"roast-plans/roast-plan-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.csv"
        import boto3  # imported lazily so local tests need no AWS SDK setup
        boto3.client("s3", region_name=os.environ.get("AWS_REGION")).put_object(
            Bucket=bucket, Key=key, Body=buf.getvalue().encode(),
            ContentType="text/csv")
        return redirect(url_for("index", message=f"Exported s3://{bucket}/{key}"))

    @app.get("/health")
    def health():
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            db_ok = True
        except Exception:
            db_ok = False
        meta = instance_metadata()
        body = {"status": "ok" if db_ok else "degraded", "database": db_ok,
                "instance_id": meta["instance_id"], "az": meta["az"]}
        return jsonify(body), (200 if db_ok else 503)

    @app.get("/stress")
    def stress():
        """Burn CPU for a few seconds to demonstrate Auto Scaling."""
        if os.environ.get("ENABLE_STRESS") != "true":
            return jsonify({"error": "disabled"}), 404
        seconds = min(max(request.args.get("seconds", 20, type=int), 1), 60)
        end = time.time() + seconds
        n = 0
        while time.time() < end:
            n += sum(i * i for i in range(10_000))
        return jsonify({"burned_seconds": seconds,
                        "instance_id": instance_metadata()["instance_id"]})

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=8000, debug=True)
