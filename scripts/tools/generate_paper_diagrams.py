import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
from pathlib import Path

# Save location
ARTIFACTS_DIR = Path("/home/chandu/.gemini/antigravity-ide/brain/405adf4b-ec6a-46d0-86d3-78507e97e0bc")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial"]

# ── 1. Figure 1: System Architecture Diagram ─────────────────────────────
fig, ax = plt.subplots(figsize=(12, 8), dpi=300)
ax.axis("off")
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)

# Main Title
ax.text(50, 96, "Figure 1: KisanMitra Decoupled Microservice System Architecture", 
        fontsize=14, fontweight="bold", ha="center", va="center", color="#111827")

# Container 1: Client Layer
rect_client = patches.FancyBboxPatch((5, 72), 90, 20, boxstyle="round,pad=0.8", ec="#2563EB", fc="#EFF6FF", lw=2)
ax.add_patch(rect_client)
ax.text(8, 88, "CLIENT LAYER", fontsize=11, fontweight="bold", color="#1E40AF")

c1 = patches.FancyBboxPatch((10, 75), 25, 10, boxstyle="round,pad=0.5", ec="#3B82F6", fc="#FFFFFF", lw=1.5)
ax.add_patch(c1)
ax.text(22.5, 80, "React 19 PWA Dashboard\n(Kannada & English)", fontsize=9, ha="center", va="center")

c2 = patches.FancyBboxPatch((40, 75), 22, 10, boxstyle="round,pad=0.5", ec="#3B82F6", fc="#FFFFFF", lw=1.5)
ax.add_patch(c2)
ax.text(51, 80, "WhatsApp Cloud API\nWebhook Engine", fontsize=9, ha="center", va="center")

c3 = patches.FancyBboxPatch((67, 75), 22, 10, boxstyle="round,pad=0.5", ec="#3B82F6", fc="#FFFFFF", lw=1.5)
ax.add_patch(c3)
ax.text(78, 80, "Telegram Bot Client\n(Async Polling)", fontsize=9, ha="center", va="center")

# Arrows Client -> Gateway
ax.annotate("", xy=(50, 68), xytext=(50, 72), arrowprops=dict(arrowstyle="->", lw=2, color="#4B5563"))
ax.text(52, 70, "HTTP / Webhook REST Requests", fontsize=8, color="#374151")

# Container 2: FastAPI Gateway Layer
rect_gw = patches.FancyBboxPatch((5, 42), 90, 24, boxstyle="round,pad=0.8", ec="#059669", fc="#ECFDF5", lw=2)
ax.add_patch(rect_gw)
ax.text(8, 62, "BACKEND API GATEWAY & ROUTER LAYER (FastAPI)", fontsize=11, fontweight="bold", color="#065F46")

r_list = [
    ("Prices Router\n/predict", 10),
    ("Farmers Router\n/declare", 27),
    ("Auth Router\n/auth/login", 44),
    ("System Router\n/health", 61),
    ("Audit Router\n/admin/logs", 78)
]
for text, x in r_list:
    r_box = patches.FancyBboxPatch((x, 46), 14, 12, boxstyle="round,pad=0.4", ec="#10B981", fc="#FFFFFF", lw=1.2)
    ax.add_patch(r_box)
    ax.text(x+7, 52, text, fontsize=8, ha="center", va="center")

# Arrows Gateway -> Services
ax.annotate("", xy=(50, 38), xytext=(50, 42), arrowprops=dict(arrowstyle="->", lw=2, color="#4B5563"))

# Container 3: Core Business Services Layer
rect_srv = patches.FancyBboxPatch((5, 18), 90, 18, boxstyle="round,pad=0.8", ec="#D97706", fc="#FFFBEB", lw=2)
ax.add_patch(rect_srv)
ax.text(8, 32, "CORE BUSINESS SERVICES LAYER", fontsize=11, fontweight="bold", color="#92400E")

s_list = [
    ("ML Service\n(ml_service.py)", 10),
    ("Farmer Service\n(farmer_service.py)", 30),
    ("Message Handler\n(message_handler.py)", 50),
    ("RAG Service\n(rag.py)", 70)
]
for text, x in s_list:
    s_box = patches.FancyBboxPatch((x, 21), 17, 8, boxstyle="round,pad=0.4", ec="#F59E0B", fc="#FFFFFF", lw=1.2)
    ax.add_patch(s_box)
    ax.text(x+8.5, 25, text, fontsize=8, ha="center", va="center")

# Arrows Services -> Database
ax.annotate("", xy=(50, 14), xytext=(50, 18), arrowprops=dict(arrowstyle="->", lw=2, color="#4B5563"))

# Container 4: Storage Layer
rect_db = patches.FancyBboxPatch((5, 2), 90, 11, boxstyle="round,pad=0.8", ec="#4F46E5", fc="#EEF2FF", lw=2)
ax.add_patch(rect_db)
ax.text(8, 10, "DATA STORAGE LAYER", fontsize=11, fontweight="bold", color="#3730A3")

db1 = patches.FancyBboxPatch((15, 4), 30, 6, boxstyle="round,pad=0.4", ec="#6366F1", fc="#FFFFFF", lw=1.2)
ax.add_patch(db1)
ax.text(30, 7, "PostgreSQL 16 Engine\n(mandi_prices, crop_declarations, audit_logs)", fontsize=8, ha="center", va="center")

db2 = patches.FancyBboxPatch((55, 4), 30, 6, boxstyle="round,pad=0.4", ec="#6366F1", fc="#FFFFFF", lw=1.2)
ax.add_patch(db2)
ax.text(70, 7, "Serialized Model Store\n(price_model.pkl, encoders.pkl)", fontsize=8, ha="center", va="center")

plt.tight_layout()
fig.savefig(ARTIFACTS_DIR / "fig1_system_architecture.png", dpi=300, bbox_inches="tight")
plt.close(fig)
print("Generated Fig 1: System Architecture")


# ── 2. Figure 2: Prediction Pipeline & Anomaly Gate Flowchart ───────────────
fig, ax = plt.subplots(figsize=(10, 10), dpi=300)
ax.axis("off")
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)

ax.text(50, 97, "Figure 2: End-to-End Prediction Pipeline & Anomaly Gate Flowchart", 
        fontsize=13, fontweight="bold", ha="center", va="center")

blocks = [
    ("Farmer Input Query\n(e.g., 'Tomato price in Kolar after 60 days')", 90, "#3B82F6", "box"),
    ("Entity Parsing & Normalization\n(Crop: Tomato, Market: Kolar, Date: t)", 78, "#10B981", "box"),
    ("Causal Feature Construction (36 Features)\n16 Baseline + 9 Spatial Spreads + 11 Weather Anomalies", 66, "#F59E0B", "box"),
    ("CatBoost Q50 Model Inference\nPredict T+60 Price (Pt+60) & Confidence Interval", 54, "#6366F1", "box"),
    ("Calculate Deviation vs 30-Day Moving Average\nDeviation = | (Pt+60 - MA30d) / MA30d |", 42, "#8B5CF6", "box"),
    ("Deviation > 30%?", 30, "#EF4444", "diamond"),
]

for text, y, color, shape in blocks:
    if shape == "box":
        box = patches.FancyBboxPatch((15, y-4), 70, 7, boxstyle="round,pad=0.5", ec=color, fc="#FFFFFF", lw=2)
        ax.add_patch(box)
        ax.text(50, y, text, fontsize=9, fontweight="bold", ha="center", va="center", color="#1F2937")
    elif shape == "diamond":
        poly = patches.Polygon([[50, y+5], [70, y], [50, y-5], [30, y]], ec=color, fc="#FEF2F2", lw=2)
        ax.add_patch(poly)
        ax.text(50, y, text, fontsize=9, fontweight="bold", ha="center", va="center", color="#991B1B")

    if y > 30:
        ax.annotate("", xy=(50, y-9), xytext=(50, y-4), arrowprops=dict(arrowstyle="->", lw=1.8, color="#4B5563"))

ax.annotate("", xy=(25, 14), xytext=(35, 30), arrowprops=dict(arrowstyle="->", lw=1.8, color="#059669"))
ax.text(26, 24, "NO (Normal Forecast)", fontsize=8, fontweight="bold", color="#059669")

box_normal = patches.FancyBboxPatch((5, 8), 40, 6, boxstyle="round,pad=0.4", ec="#10B981", fc="#ECFDF5", lw=1.5)
ax.add_patch(box_normal)
ax.text(25, 11, "Deliver Forecast to Farmer\n(WhatsApp / PWA Response)", fontsize=8, ha="center", va="center", color="#065F46")

ax.annotate("", xy=(75, 14), xytext=(65, 30), arrowprops=dict(arrowstyle="->", lw=1.8, color="#DC2626"))
ax.text(72, 24, "YES (Anomaly Alert)", fontsize=8, fontweight="bold", color="#DC2626")

box_anomaly = patches.FancyBboxPatch((55, 8), 40, 6, boxstyle="round,pad=0.4", ec="#EF4444", fc="#FEF2F2", lw=1.5)
ax.add_patch(box_anomaly)
ax.text(75, 11, "Flag Alert in Admin Sandbox\n(Human-in-the-Loop Validation)", fontsize=8, ha="center", va="center", color="#991B1B")

plt.tight_layout()
fig.savefig(ARTIFACTS_DIR / "fig2_prediction_pipeline_flowchart.png", dpi=300, bbox_inches="tight")
plt.close(fig)
print("Generated Fig 2: Prediction Pipeline Flowchart")


# ── 3. Figure 3: Database ER Diagram ──────────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 8), dpi=300)
ax.axis("off")
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)

ax.text(50, 96, "Figure 3: KisanMitra PostgreSQL 16 Entity-Relationship (ER) Schema", 
        fontsize=13, fontweight="bold", ha="center", va="center")

tables = [
    ("mandi_prices", 10, 55, [
        "id: Integer [PK]",
        "state: String(100)",
        "district: String(100) [IX]",
        "market: String(150) [IX]",
        "commodity: String(150) [IX]",
        "arrival_date: DateTime [IX]",
        "modal_price: Float",
        "arrivals_tonnes: Float"
    ]),
    ("farmers", 40, 55, [
        "id: Integer [PK]",
        "name: String(255)",
        "phone: String(20) [UK, IX]",
        "district: String(100)",
        "taluk: String(100)",
        "created_at: DateTime"
    ]),
    ("crop_declarations", 70, 55, [
        "id: Integer [PK]",
        "farmer_name: String(255)",
        "phone: String(20) [IX]",
        "district: String(100) [IX]",
        "crop: String(100) [IX]",
        "area_acres: Float",
        "season: String(50)",
        "declared_at: DateTime"
    ]),
    ("knowledge_chunks", 10, 10, [
        "id: Integer [PK]",
        "crop: String(100) [IX]",
        "category: String(100) [IX]",
        "districts: JSONB",
        "content: Text",
        "embedding: Vector(768)",
        "created_at: DateTime"
    ]),
    ("audit_logs", 40, 10, [
        "id: Integer [PK]",
        "admin_username: String [IX]",
        "action: String [IX]",
        "target: String",
        "ip_address: String",
        "created_at: DateTime [IX]"
    ]),
    ("revoked_tokens", 70, 10, [
        "id: Integer [PK]",
        "jti: String [UK, IX]",
        "revoked_at: DateTime",
        "expires_at: DateTime [IX]"
    ])
]

for title, x, y, fields in tables:
    header = patches.Rectangle((x, y+24), 24, 5, ec="#1E3A8A", fc="#1E40AF", lw=1.5)
    ax.add_patch(header)
    ax.text(x+12, y+26.5, title, fontsize=9, fontweight="bold", ha="center", va="center", color="#FFFFFF")
    
    body = patches.Rectangle((x, y), 24, 24, ec="#1E3A8A", fc="#F8FAFC", lw=1.5)
    ax.add_patch(body)
    
    for idx, f in enumerate(fields):
        ax.text(x+1.5, y+21 - idx*2.8, f, fontsize=7.5, ha="left", va="center", color="#334155")

ax.annotate("", xy=(40, 68), xytext=(34, 68), arrowprops=dict(arrowstyle="<->", lw=1.5, color="#2563EB"))
ax.text(37, 70, "1 : N", fontsize=8, fontweight="bold", color="#2563EB")

plt.tight_layout()
fig.savefig(ARTIFACTS_DIR / "fig3_database_er_diagram.png", dpi=300, bbox_inches="tight")
plt.close(fig)
print("Generated Fig 3: Database ER Diagram")


# ── 4. Figure 4: Empirical Ablation Performance Chart ──────────────────────
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5), dpi=300)

stages = ["M5 Baseline\n(Random Forest)", "Stage A\n(CatBoost)", "Stage D1\n(+ Spatial)", "Stage D3\n(+ Weather)", "Stage D4\n(CatBoost Q50)"]
mapes = [38.86, 35.73, 35.86, 35.35, 34.60]
colors = ["#94A3B8", "#64748B", "#3B82F6", "#059669", "#10B981"]

bars1 = ax1.bar(stages, mapes, color=colors, width=0.55, edgecolor="#1E293B", linewidth=1.2)
ax1.set_title("Global Forecast MAPE (%) Across Ablation Ladder\n(Test N = 44,572 Rows)", fontsize=11, fontweight="bold", pad=12)
ax1.set_ylabel("Mean Absolute Percentage Error (%)", fontsize=10, fontweight="bold")
ax1.set_ylim(30, 42)
ax1.grid(axis="y", linestyle="--", alpha=0.5)

for bar in bars1:
    yval = bar.get_height()
    ax1.text(bar.get_x() + bar.get_width()/2.0, yval + 0.3, f"{yval:.2f}%", ha="center", va="bottom", fontsize=9.5, fontweight="bold")

metrics = ["Crash MAE (₹/q)", "Crash Signed Error (₹/q)"]
rmse_vals = [475.59, 193.32]
q50_vals = [408.60, 45.09]

x = np.arange(len(metrics))
width = 0.35

rects1 = ax2.bar(x - width/2, rmse_vals, width, label="Standard RMSE (D3)", color="#EF4444", edgecolor="#7F1D1D", lw=1.2)
rects2 = ax2.bar(x + width/2, q50_vals, width, label="CatBoost Q50 (Median)", color="#10B981", edgecolor="#065F46", lw=1.2)

ax2.set_title("Post-Harvest Crash Mitigation Audit\n(N = 13,320 Price Crash Sessions)", fontsize=11, fontweight="bold", pad=12)
ax2.set_ylabel("Error Metric (₹ / quintal)", fontsize=10, fontweight="bold")
ax2.set_xticks(x)
ax2.set_xticklabels(metrics, fontsize=10, fontweight="bold")
ax2.set_ylim(0, 550)
ax2.legend(frameon=True, facecolor="#F8FAFC", edgecolor="#CBD5E1")
ax2.grid(axis="y", linestyle="--", alpha=0.5)

for bar in rects1:
    yval = bar.get_height()
    ax2.text(bar.get_x() + bar.get_width()/2.0, yval + 8, f"₹{yval:.2f}", ha="center", va="bottom", fontsize=9, fontweight="bold", color="#7F1D1D")

for bar in rects2:
    yval = bar.get_height()
    ax2.text(bar.get_x() + bar.get_width()/2.0, yval + 8, f"₹{yval:.2f}", ha="center", va="bottom", fontsize=9, fontweight="bold", color="#065F46")

ax2.text(0, 490, "14.1% MAE Drop ↓", ha="center", fontsize=8.5, fontweight="bold", color="#065F46")
ax2.text(1, 210, "76.7% Bias Reduction ↓", ha="center", fontsize=8.5, fontweight="bold", color="#065F46")

plt.tight_layout()
fig.savefig(ARTIFACTS_DIR / "fig4_empirical_ablation_performance.png", dpi=300, bbox_inches="tight")
plt.close(fig)
print("Generated Fig 4: Empirical Ablation Performance Chart")


# ── 5. Figure 5: 5-Fold Walk-Forward Temporal CV Stability ───────────────────
fig, ax = plt.subplots(figsize=(9, 5), dpi=300)

years = ["2021\n(N=9,467)", "2022\n(N=11,293)", "2023\n(N=10,297)", "2024\n(N=9,826)", "2025\n(N=5,416)"]
rmse_mape = [38.94, 36.75, 39.10, 30.07, 36.32]
q50_mape = [33.95, 33.99, 35.02, 31.16, 31.80]

x = np.arange(len(years))
width = 0.35

rects1 = ax.bar(x - width/2, rmse_mape, width, label="CatBoost RMSE MAPE (%)", color="#64748B", edgecolor="#1E293B", lw=1.2)
rects2 = ax.bar(x + width/2, q50_mape, width, label="CatBoost Q50 MAPE (%)", color="#10B981", edgecolor="#065F46", lw=1.2)

ax.set_title("5-Fold Walk-Forward Temporal Cross-Validation Stability\n(CatBoost RMSE vs CatBoost Q50 across yearly cutoffs)", fontsize=11, fontweight="bold", pad=12)
ax.set_ylabel("Mean Absolute Percentage Error (%)", fontsize=10, fontweight="bold")
ax.set_xticks(x)
ax.set_xticklabels(years, fontsize=9.5, fontweight="bold")
ax.set_ylim(20, 45)
ax.legend(frameon=True, facecolor="#F8FAFC", edgecolor="#CBD5E1")
ax.grid(axis="y", linestyle="--", alpha=0.5)

for bar in rects1:
    yval = bar.get_height()
    ax.text(bar.get_x() + bar.get_width()/2.0, yval + 0.4, f"{yval:.2f}%", ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="#334155")

for bar in rects2:
    yval = bar.get_height()
    ax.text(bar.get_x() + bar.get_width()/2.0, yval + 0.4, f"{yval:.2f}%", ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="#065F46")

plt.tight_layout()
fig.savefig(ARTIFACTS_DIR / "fig5_walk_forward_cv_stability.png", dpi=300, bbox_inches="tight")
plt.close(fig)
print("Generated Fig 5: Walk-Forward CV Stability Chart")

print("All 5 original high-resolution paper diagrams successfully generated!")
