# Data Point Significance Guide

Kab dekhna hai, kya signal milta hai, kaise use karein.  
(Premarket / ORB / bias planning for Nifty & BankNifty)

---

## 1. Meta

| Column | Significance | Kab dekhna |
|--------|--------------|------------|
| **Date / Day** | Seasonality (Mon bias, expiry week, Friday profit-booking) | Roz plan banate waqt |
| **Trading Day** | Holiday/weekend pe signals ignore; next session plan | Calendar open pe |
| **Last Updated** | Data freshness — stale OI se galat bias | Refresh ke baad |
| **OI Report Date** | OI kis session ka hai (usually previous close) | ~7–7:30 PM ke baad |

---

## 2. India indices

| Column | Significance | Kab dekhna |
|--------|--------------|------------|
| **Nifty 50 Close** | Gap base + trend reference. Expected gap = GIFT − Nifty close | Pre-market pehle number |
| **BankNifty Close** | Banks heavy din / which index trade. FII flow often bank-linked | Pre-market + open |
| **Sensex (BSE)** | BSE 30 broad market. Nifty se confirm: dono same direction → cleaner bias; diverge → caution | Pre-market + open |
| **India VIX** | **Low VIX** → range / mean-reversion friendly. **High VIX** → wide ranges, bigger SL, premium rich options | Pre-market; event weeks (Budget, RBI, US CPI) pe critical |

**Rule of thumb**
- VIX &lt; 13: quieter, ORB tighter  
- VIX 13–18: normal  
- VIX &gt; 18–20: size down, expect spikes  

---

## 3. GIFT + Gap (pre-market core)

| Column | Significance | Kab dekhna |
|--------|--------------|------------|
| **GIFT Nifty** | SGX/NSE IX overnight lead — sabse strong free pre-open signal (Upstox se auto) | **Sabse pehle** subah (Asia + GIFT open) |
| **Expected Gap Pts / %** | Open pe kitna jump/dip expect | GIFT + Nifty close dono milte hi |
| **Gap Category** | Small / Medium / Large → alag ORB rules | Gap calc ke turant baad |

**Typical use**
- Small gap: fade / range ORB possible  
- Large gap: trend day / gap-fill wait; don’t fight open blindly  
- GIFT flat + Europe/US weak: caution even if India closed green  

---

## 4. US markets (overnight bias)

| Column | Significance | Kab dekhna |
|--------|--------------|------------|
| **Dow Jones** | Classic US risk mood | India open se pehle (US already closed) |
| **S&P 500** | Global equity beta — broad risk-on/off | Same |
| **Nasdaq / US Tech** | Growth/tech appetite; risk-on when Nasdaq leads | Same; IT-heavy sessions |

**How to read**
- US green + Asia green → bullish open bias  
- US red hard → Nifty often soft open even if GIFT mild  
- Nasdaq weak + India IT weak correlation on some days  

---

## 5. Asia markets

| Column | Significance | Kab dekhna |
|--------|--------------|------------|
| **Nikkei 225** | Japan risk; early Asia lead | **6–8 AM IST** window |
| **Hang Seng** | China/HK risk; FII Asia mood | Same; China news days pe weight badhao |

**How to read**
- Asia crash + GIFT down → strong gap-down risk  
- Asia flat, GIFT up → cleaner bullish open  

---

## 6. Europe markets (new)

| Column | Significance | Kab dekhna |
|--------|--------------|------------|
| **FTSE 100 (UK)** | London risk; commodity/ pound linked names | India morning (Europe open overlap / prior close) |
| **DAX (Germany)** | Eurozone industrial / export risk | Same |
| **CAC 40 (France)** | DAX ke saath Europe confirmation | Same |
| **EURO STOXX 50** | Broad Europe blue-chip | Same |

**Why Europe matters for India**
- Europe open **overlaps** early India trade (≈12:00–3:30 PM IST full overlap later)  
- Pre-market: previous Europe close + early Europe futures mood  
- US + Europe dono red → global risk-off; don’t force long ORB  
- Europe green after weak Asia → recovery bias mid-session  

---

## 7. Cash flow (FII / DII ₹ Cr)

| Column | Significance | Kab dekhna |
|--------|--------------|------------|
| **FII Cash Net** | Foreign money cash market me net buy/sell | Evening provisional; **next morning** better |
| **DII Cash Net** | Mutual fund/insurance domestic absorption | Jab FII sell kare — DII kitna absorb kar raha |

**How to read**
- FII heavy sell + DII heavy buy → often range / support, not free-fall  
- FII + DII dono sell → weak structure  
- FII buy streak → medium-term bullish backdrop (not intraday entry alone)  

---

## 8. FII Index Futures OI (NSE official) — real edge

Source: NSE **F&O Participant wise Open Interest** CSV  
`fao_participant_oi_DDMMYYYY.csv`  
Usually available **~7:00–7:30 PM IST** after market.

| Column | Significance | Kab dekhna |
|--------|--------------|------------|
| **FII Idx Fut Long** | Contracts long — number **(long % of FII fut OI)** | Har trading day evening |
| **FII Idx Fut Short** | Contracts short — number **(short %)** | Same |
| **FII Long % / Short %** | Positioning split (e.g. Long 8%, Short 92%) | Same — *percentage brackets* |
| **FII Net (L−S)** | Directional net | Same |
| **FII Long/Short Ratio** | &lt;1 = net short, &gt;1 = net long | Same |
| **FII Idx Opt PCR (short)** | Put short / Call short on FII index options | Same |
| **DII Idx Fut L/S** | DII often long futures vs cash hedges | Context with FII |

### Display format
```
Long:  26,357 (8.36%)
Short: 2,89,069 (91.64%)
```
= actual contracts + share of FII’s own index-futures book.

### How traders use it
1. **FII heavily short futures** (short % high, ratio &lt;&lt; 1)  
   - Often bearish / hedged. Don’t blindly buy dips without cash DII support.  
2. **FII covering shorts** (short OI falling day-on-day)  
   - Squeeze / relief rally risk.  
3. **FII adding long**  
   - Trend continuation bias next sessions.  
4. **Combine with cash**  
   - Cash sell + futures short = aggressive bearish  
   - Cash sell + futures long = hedge / stock specific  

**Most retail miss this** — cash FII alone incomplete; futures OI shows *positioning*.

### Next-day match (dashboard FII OI tab)

Dashboard **only shows FII** (no DII / Pro / Client) for last ~1 week.

| Concept | Meaning |
|---------|---------|
| **OI Date T** | Evening report after session T closes |
| **Bias signal** | Net (Long−Short) &gt; 0 → BULLISH next day; &lt; 0 → BEARISH |
| **Flow signal** | ΔNet day-over-day: rising net = covering/bullish; falling net = more short/bearish |
| **Next day %** | Nifty close move from T → next session |
| **Match** | Did signal direction agree with next day UP/DOWN? |
| **Bias accuracy** | % of scored days bias was correct |
| **Flow accuracy** | % of scored days flow (ΔNet) was correct |

Example: 15-Jul OI net short (BEARISH) → 16-Jul Nifty **UP** → Bias **MISS**, but if ΔNet improved (covering) Flow may still **MATCH**.

---

## 9. Sentiment helpers

| Column | Significance | Kab dekhna |
|--------|--------------|------------|
| **PCR** | Put/Call ratio quick bias | Secondary; not alone |
| **Sentiment Score** | 0–100 composite | Quick scan only |

---

## Suggested daily checklist (time order)

| Time (IST) | Check |
|------------|--------|
| **6:30–8:00** | GIFT, Asia (Nikkei, HSI), previous US close |
| **8:00–9:00** | Europe prior close / early Europe, VIX, Gap category |
| **9:00–9:15** | Final bias: Gap + global stack + yesterday FII OI |
| **9:15–9:30** | ORB only if plan matches gap category |
| **~19:00–19:30** | Download/auto-pull **NSE participant OI** → update Long/Short % |
| **Night** | Cash FII/DII provisional; note for next morning |

---

## Free sources (no bill)

| Data | Source | Cost |
|------|--------|------|
| India / US / Asia / Europe prices | Yahoo + Upstox | Free |
| GIFT Nifty | Upstox `GLOBAL_INDEX\|SGX NIFTY` | Free API |
| FII/DII cash | MrChartist free API | Free |
| FII OI long/short | **NSE official CSV** | Free |
| History | Local JSON 90d daily → weekly | Free disk |

---

## Gap category defaults (Config)

| Category | |Gap %| |
|----------|--------|
| Small | &lt; 0.30% |
| Medium | 0.30% – 0.70% |
| Large | ≥ 0.70% |

Adjust for your ORB system if needed.
