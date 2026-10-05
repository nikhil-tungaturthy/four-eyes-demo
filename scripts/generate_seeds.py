"""Generate seeds/raw_executions.csv: synthetic and deterministic, so it can be regenerated any time.

Three member-months sit exactly on the Tier 1 line (5,000,000 equity + ETF shares).
Those are the rows a ">=" vs ">" change to the tier rule would move.
"""
import csv
import random

random.seed(42)
EQUITIES, ETFS = ["AAPL", "MSFT", "NVDA", "JPM"], ["QQQ", "SPY"]
MEMBERS = [f"M{i:02d}" for i in range(1, 13)]
BOUNDARY = {("M03", 7): 5_000_000, ("M07", 8): 5_000_000, ("M05", 9): 5_000_000}
SIZES = [300_000, 1_800_000, 6_500_000]  # lands a member in Tier 3, 2, or 1
rows = []


def add(member, month, product, symbol, qty):
    ts = f"2026-{month:02d}-{random.randint(1, 28):02d} {random.randint(9, 15):02d}:{random.randint(0, 59):02d}:00"
    flag = random.choices(["A", "R"], weights=[40, 60])[0]  # A adds liquidity (rebate), R removes it (fee)
    rows.append([f"E{len(rows) + 1:06d}", ts, member, symbol, product, flag, qty])


for month in (7, 8, 9):
    for member in MEMBERS:
        target = BOUNDARY.get((member, month), random.choice(SIZES))
        shares = 0
        while shares < target:
            qty = min(random.choice([10_000, 25_000, 50_000]), target - shares)
            symbol = random.choice(EQUITIES + ETFS)
            add(member, month, "etf" if symbol in ETFS else "equity", symbol, qty)
            shares += qty
        for _ in range(random.randint(5, 15)):  # options are priced per contract and don't count toward tiers
            add(member, month, "option", random.choice(EQUITIES), random.randint(10, 500))

with open("seeds/raw_executions.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["execution_id", "executed_at", "member_id", "symbol", "product", "liquidity_flag", "quantity"])
    writer.writerows(rows)

print(f"wrote {len(rows)} executions")
