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

# ── 1. Slide 2: Problem Statement & Smallholder Vicious Cycle Diagram ────
fig, ax = plt.subplots(figsize=(10, 6), dpi=300)
ax.axis("off")
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)

ax.text(50, 93, "The Smallholder Market Price Crash Cycle in Karnataka", 
        fontsize=13, fontweight="bold", ha="center", va="center", color="#111827")

stages = [
    ("1. High Spot Price Signal\n(June: Tomato @ Rs 80/kg)", 15, 60, "#2563EB"),
    ("2. Uncoordinated Overplanting\n(July: Thousands sow Tomato)", 40, 60, "#D97706"),
    ("3. Massive Harvest Glut\n(August: Market Flooded)", 65, 60, "#DC2626"),
    ("4. Severe Price Collapse\n(August: Price drops to Rs 4/kg)", 90, 60, "#7F1D1D")
]

for title, x, y, col in stages:
    box = patches.FancyBboxPatch((x-10, y-12), 20, 24, boxstyle="round,pad=0.6", ec=col, fc="#FFFFFF", lw=2)
    ax.add_patch(box)
    ax.text(x, y, title, fontsize=8.5, fontweight="bold", ha="center", va="center", color="#1F2937")

# Cycle Arrows
ax.annotate("", xy=(30, 60), xytext=(25, 60), arrowprops=dict(arrowstyle="->", lw=2, color="#4B5563"))
ax.annotate("", xy=(55, 60), xytext=(50, 60), arrowprops=dict(arrowstyle="->", lw=2, color="#4B5563"))
ax.annotate("", xy=(80, 60), xytext=(75, 60), arrowprops=dict(arrowstyle="->", lw=2, color="#4B5563"))

# Bottom Intervention Callout
rect_int = patches.FancyBboxPatch((15, 10), 70, 22, boxstyle="round,pad=0.8", ec="#059669", fc="#ECFDF5", lw=2)
ax.add_patch(rect_int)
ax.text(50, 25, "KisanMitra Proactive Intervention", fontsize=11, fontweight="bold", color="#065F46", ha="center")
ax.text(50, 16, "Intercepts at Step 2 (Pre-Sowing) by delivering T+60 Forward Price Forecasts\nand 31-District Saturation Warnings via WhatsApp & PWA in Kannada/English.", 
        fontsize=8.5, ha="center", color="#047857")

plt.tight_layout()
fig.savefig(ARTIFACTS_DIR / "pres_slide2_problem_statement.png", dpi=300, bbox_inches="tight")
plt.close(fig)
print("Generated pres_slide2_problem_statement.png")


# ── 2. Slide 6: UML Use Case Diagram Graphic ──────────────────────────────
fig, ax = plt.subplots(figsize=(10, 7), dpi=300)
ax.axis("off")
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)

ax.text(50, 94, "UML Use Case Diagram — KisanMitra System", fontsize=13, fontweight="bold", ha="center")

ax.text(10, 75, "Smallholder\nFarmer", fontsize=9, fontweight="bold", ha="center", color="#1E40AF")
ax.text(10, 25, "Extension Officer\n/ Admin", fontsize=9, fontweight="bold", ha="center", color="#065F46")

sys_box = patches.Rectangle((25, 5), 65, 82, ec="#475569", fc="#F8FAFC", lw=1.8, linestyle="--")
ax.add_patch(sys_box)
ax.text(57.5, 83, "KisanMitra Platform Boundary", fontsize=9, fontweight="bold", color="#334155", ha="center")

usecases = [
    ("UC1: Query T+60 Price Forecast", 57.5, 72, "#3B82F6"),
    ("UC2: Submit Sowing Declaration", 57.5, 60, "#3B82F6"),
    ("UC3: Check District Saturation", 57.5, 48, "#3B82F6"),
    ("UC4: Request Agronomy Advisory", 57.5, 36, "#10B981"),
    ("UC5: Review Price Anomaly Alerts", 57.5, 24, "#EF4444"),
    ("UC6: Audit DPDP Compliance Logs", 57.5, 12, "#8B5CF6")
]

for label, x, y, col in usecases:
    ellipse = patches.Ellipse((x, y), 35, 8, ec=col, fc="#FFFFFF", lw=1.5)
    ax.add_patch(ellipse)
    ax.text(x, y, label, fontsize=8, fontweight="bold", ha="center", va="center", color="#1E293B")

ax.plot([10, 40], [70, 72], color="#2563EB", lw=1.2)
ax.plot([10, 40], [70, 60], color="#2563EB", lw=1.2)
ax.plot([10, 40], [70, 48], color="#2563EB", lw=1.2)
ax.plot([10, 40], [70, 36], color="#2563EB", lw=1.2)

ax.plot([10, 40], [30, 48], color="#059669", lw=1.2)
ax.plot([10, 40], [30, 24], color="#059669", lw=1.2)
ax.plot([10, 40], [30, 12], color="#059669", lw=1.2)

plt.tight_layout()
fig.savefig(ARTIFACTS_DIR / "pres_slide6_use_case_diagram.png", dpi=300, bbox_inches="tight")
plt.close(fig)
print("Generated pres_slide6_use_case_diagram.png")


# ── 3. Slide 7: UML Class Diagram Graphic ─────────────────────────────────
fig, ax = plt.subplots(figsize=(11, 7), dpi=300)
ax.axis("off")
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)

ax.text(50, 95, "UML Class Diagram — Domain & Service Architecture", fontsize=13, fontweight="bold", ha="center")

classes = [
    ("MandiPrice", 10, 52, ["+int id", "+string district", "+string market", "+string commodity", "+datetime arrival_date", "+float modal_price"], "#1E40AF"),
    ("Farmer", 40, 52, ["+int id", "+string name", "+string phone", "+string district", "+string taluk", "+datetime created_at"], "#065F46"),
    ("CropDeclaration", 70, 52, ["+int id", "+string phone", "+string district", "+string crop", "+float area_acres", "+string season"], "#D97706"),
    ("MLService", 25, 10, ["+load_model()", "+predict_price_60d()", "+construct_36_features()", "+evaluate_anomaly_gate()"], "#6B21A8"),
    ("FarmerService", 60, 10, ["+register_declaration()", "+check_idempotency()", "+compute_district_saturation()"], "#4C1D95")
]

for name, x, y, members, col in classes:
    rect_h = patches.Rectangle((x, y+22), 24, 5, ec=col, fc=col, lw=1.5)
    ax.add_patch(rect_h)
    ax.text(x+12, y+24.5, name, fontsize=8.5, fontweight="bold", color="#FFFFFF", ha="center", va="center")
    
    rect_b = patches.Rectangle((x, y), 24, 22, ec=col, fc="#F8FAFC", lw=1.5)
    ax.add_patch(rect_b)
    for idx, m in enumerate(members):
        ax.text(x+1.5, y+18.5 - idx*3.2, m, fontsize=7.5, color="#334155")

ax.plot([34, 40], [63, 63], color="#475569", lw=1.5)
ax.text(37, 65, "1..*", fontsize=7, color="#475569")

plt.tight_layout()
fig.savefig(ARTIFACTS_DIR / "pres_slide7_class_diagram.png", dpi=300, bbox_inches="tight")
plt.close(fig)
print("Generated pres_slide7_class_diagram.png")


# ── 4. Slide 8: UML Activity Diagram Graphic ──────────────────────────────
fig, ax = plt.subplots(figsize=(9, 8), dpi=300)
ax.axis("off")
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)

ax.text(50, 96, "UML Activity Diagram — Price Prediction & Anomaly Gate", fontsize=12, fontweight="bold", ha="center")

ax.plot(50, 90, "o", ms=12, color="#1E293B")

act_nodes = [
    ("Receive Price Forecast Query", 80, "#3B82F6"),
    ("Resolve Commodity & Market Entities", 68, "#10B981"),
    ("Construct 36 Spatial & Weather Features", 56, "#F59E0B"),
    ("Run CatBoost Q50 Model Inference", 44, "#6366F1"),
    ("Calculate Deviation vs 30-Day Moving Avg", 32, "#8B5CF6")
]

for text, y, col in act_nodes:
    box = patches.FancyBboxPatch((20, y-4), 60, 6, boxstyle="round,pad=0.4", ec=col, fc="#FFFFFF", lw=1.5)
    ax.add_patch(box)
    ax.text(50, y, text, fontsize=8, fontweight="bold", ha="center", va="center", color="#1F2937")

ax.annotate("", xy=(50, 83), xytext=(50, 88), arrowprops=dict(arrowstyle="->", lw=1.5, color="#4B5563"))
ax.annotate("", xy=(50, 71), xytext=(50, 76), arrowprops=dict(arrowstyle="->", lw=1.5, color="#4B5563"))
ax.annotate("", xy=(50, 59), xytext=(50, 64), arrowprops=dict(arrowstyle="->", lw=1.5, color="#4B5563"))
ax.annotate("", xy=(50, 47), xytext=(50, 52), arrowprops=dict(arrowstyle="->", lw=1.5, color="#4B5563"))
ax.annotate("", xy=(50, 35), xytext=(50, 40), arrowprops=dict(arrowstyle="->", lw=1.5, color="#4B5563"))

poly = patches.Polygon([[50, 24], [65, 18], [50, 12], [35, 18]], ec="#EF4444", fc="#FEF2F2", lw=1.5)
ax.add_patch(poly)
ax.text(50, 18, "Deviation > 30%?", fontsize=7.5, fontweight="bold", ha="center", va="center", color="#991B1B")
ax.annotate("", xy=(50, 24), xytext=(50, 28), arrowprops=dict(arrowstyle="->", lw=1.5, color="#4B5563"))

box_pass = patches.FancyBboxPatch((5, 2), 35, 6, boxstyle="round,pad=0.4", ec="#10B981", fc="#ECFDF5", lw=1.2)
ax.add_patch(box_pass)
ax.text(22.5, 5, "Send Forecast to Farmer", fontsize=7.5, ha="center", va="center", color="#065F46")

box_flag = patches.FancyBboxPatch((60, 2), 35, 6, boxstyle="round,pad=0.4", ec="#EF4444", fc="#FEF2F2", lw=1.2)
ax.add_patch(box_flag)
ax.text(77.5, 5, "Flag Alert in Admin Sandbox", fontsize=7.5, ha="center", va="center", color="#991B1B")

ax.annotate("", xy=(22.5, 8), xytext=(38, 18), arrowprops=dict(arrowstyle="->", lw=1.5, color="#059669"))
ax.annotate("", xy=(77.5, 8), xytext=(62, 18), arrowprops=dict(arrowstyle="->", lw=1.5, color="#DC2626"))

plt.tight_layout()
fig.savefig(ARTIFACTS_DIR / "pres_slide8_activity_diagram.png", dpi=300, bbox_inches="tight")
plt.close(fig)
print("Generated pres_slide8_activity_diagram.png")


# ── 5. Slide 12: High-Fidelity UI Wireframes Diagram ──────────────────────
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 6.5), dpi=300)

# Left Subplot: WhatsApp Conversational Bot Wireframe
ax1.axis("off")
ax1.set_xlim(0, 100)
ax1.set_ylim(0, 100)

phone = patches.FancyBboxPatch((10, 5), 80, 90, boxstyle="round,pad=1.0", ec="#1E293B", fc="#F1F5F9", lw=2)
ax1.add_patch(phone)
ax1.text(50, 90, "WhatsApp — KisanMitra Assistant", fontsize=10, fontweight="bold", color="#0F172A", ha="center")

msg1 = patches.FancyBboxPatch((35, 70), 50, 12, boxstyle="round,pad=0.5", ec="#86EFAC", fc="#DCFCE7", lw=1.2)
ax1.add_patch(msg1)
ax1.text(60, 76, "Kolaralli 60 dinagala nantara\nTomato bele estiruttatte?", fontsize=8, color="#14532D", ha="center", va="center")

msg2 = patches.FancyBboxPatch((15, 25), 65, 38, boxstyle="round,pad=0.5", ec="#CBD5E1", fc="#FFFFFF", lw=1.2)
ax1.add_patch(msg2)
bot_text = (
    "*KisanMitra T+60 Forward Forecast*\n\n"
    "Market: Kolar Mandi\n"
    "Crop: Tomato\n"
    "Predicted Price: Rs 2,150 / quintal\n"
    "Confidence Range: Rs 1,850 - Rs 2,400\n\n"
    "Saturation Alert: Kolar district is\n"
    "at 78% Sowing Saturation (HIGH RISK)."
)
ax1.text(47.5, 44, bot_text, fontsize=7.5, color="#0F172A", ha="center", va="center")

ax1.set_title("A. Multilingual WhatsApp Chatbot Interface", fontsize=11, fontweight="bold", pad=10)


# Right Subplot: React 19 PWA Saturation Map Wireframe
ax2.axis("off")
ax2.set_xlim(0, 100)
ax2.set_ylim(0, 100)

dashboard = patches.Rectangle((5, 5), 90, 90, ec="#334155", fc="#F8FAFC", lw=1.8)
ax2.add_patch(dashboard)

head = patches.Rectangle((5, 83), 90, 12, ec="#1E40AF", fc="#1E3A8A", lw=1)
ax2.add_patch(head)
ax2.text(50, 89, "KisanMitra Admin Dashboard — 31 District Saturation Monitor", fontsize=9, fontweight="bold", color="#FFFFFF", ha="center")

map_box = patches.Rectangle((10, 15), 50, 62, ec="#94A3B8", fc="#E2E8F0", lw=1)
ax2.add_patch(map_box)
ax2.text(35, 46, "Interactive Leaflet Map\n(31 Districts of Karnataka)\n\nGreen: <50% Saturation\nYellow: 50-75% Saturation\nRed: >75% High Risk", 
         fontsize=7.5, color="#334155", ha="center", va="center")

side_box = patches.Rectangle((63, 15), 28, 62, ec="#94A3B8", fc="#FFFFFF", lw=1)
ax2.add_patch(side_box)
ax2.text(77, 72, "District Analytics", fontsize=8, fontweight="bold", color="#1E293B", ha="center")
ax2.text(77, 50, "Kolar District:\nTomato: 78% (HIGH)\nMaize: 42% (OK)\n\nChikkaballapur:\nTomato: 84% (HIGH)\n\nBelagavi:\nPotato: 61% (MED)", 
         fontsize=7, color="#475569", ha="center", va="center")

ax2.set_title("B. Progressive Web App (PWA) Admin Dashboard", fontsize=11, fontweight="bold", pad=10)

plt.tight_layout()
fig.savefig(ARTIFACTS_DIR / "pres_slide12_ui_wireframes.png", dpi=300, bbox_inches="tight")
plt.close(fig)
print("Generated pres_slide12_ui_wireframes.png")

print("All presentation slide image graphics successfully generated!")
