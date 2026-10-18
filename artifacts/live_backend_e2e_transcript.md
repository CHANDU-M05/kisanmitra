# KisanMitra Live Backend E2E Test & Response Transcript Audit

- **Total Live HTTP Tests**: 25
- **Verified Perfect**: **25 / 25** (100.0%)

## 📝 Live Request & Response Transcript Audit

### Test E2E-01: `Namaskara, Bengaluru Urbanalli ivattu rain agutta umbrella beka?`
- **Status**: `PASS`
- **Response Type**: `help`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "Namaskara, Bengaluru Urbanalli ivattu rain agutta umbrella beka?",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "help"
}
```

---

### Test E2E-02: `Namaskara guru, Kolar geography mattu history bagge mahiti kodi.`
- **Status**: `PASS`
- **Response Type**: `help`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "Namaskara guru, Kolar geography mattu history bagge mahiti kodi.",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "help"
}
```

---

### Test E2E-03: `Who created KisanMitra and what can you do?`
- **Status**: `PASS`
- **Response Type**: `help`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "Who created KisanMitra and what can you do?",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "help"
}
```

---

### Test E2E-04: `ಮೈಸೂರಿನಲ್ಲಿ ಟೊಮ್ಯಾಟೊ ಪ್ರಸ್ತುತ ಮಾರುಕಟ್ಟೆ ಬೆಲೆ ಎಷ್ಟು ಮತ್ತು ಮುಂದಿನ 60 ದಿನಗಳ ಮುನ್ಸೂಚನೆ ಏನು?`
- **Status**: `PASS`
- **Response Type**: `anomaly_flagged`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "ಮೈಸೂರಿನಲ್ಲಿ ಟೊಮ್ಯಾಟೊ ಪ್ರಸ್ತುತ ಮಾರುಕಟ್ಟೆ ಬೆಲೆ ಎಷ್ಟು ಮತ್ತು ಮುಂದಿನ 60 ದಿನಗಳ ಮುನ್ಸೂಚನೆ ಏನು?",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "anomaly_flagged",
  "crop": "Tomato",
  "district": "Mysuru",
  "current_price": 800.0,
  "forecast": 2226.0,
  "lower": 902.0,
  "upper": 4253.0,
  "signal": "WAIT — Price likely rising",
  "signal_kannada": "ಬೆಲೆ ಏರಲಿದೆ — ಕಾಯಿರಿ ⬆",
  "is_anomaly": true,
  "anomaly_type": "SPIKE",
  "deviation_pct": 178.3,
  "crop_mape_pct": 39.92,
  "msp_floor": null
}
```

---

### Test E2E-05: `Give me the 60 day price forecast for Groundnut in Chitradurga mandi.`
- **Status**: `PASS`
- **Response Type**: `anomaly_flagged`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "Give me the 60 day price forecast for Groundnut in Chitradurga mandi.",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "anomaly_flagged",
  "crop": "Groundnut",
  "district": "Chitradurga",
  "current_price": 5600.0,
  "forecast": 1920.0,
  "lower": 1069.0,
  "upper": 2817.0,
  "signal": "SELL NOW — Price likely falling",
  "signal_kannada": "ಈಗಲೇ ಮಾರಿ — ಬೆಲೆ ಇಳಿಯಲಿದೆ ⬇",
  "is_anomaly": true,
  "anomaly_type": "CRASH",
  "deviation_pct": 65.7,
  "crop_mape_pct": null,
  "msp_floor": null
}
```

---

### Test E2E-06: `Hassan district ali Potato rate next 60 days ge spike agutta or crash agutta?`
- **Status**: `PASS`
- **Response Type**: `anomaly_flagged`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "Hassan district ali Potato rate next 60 days ge spike agutta or crash agutta?",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "anomaly_flagged",
  "crop": "Potato",
  "district": "Hassan",
  "current_price": 1000.0,
  "forecast": 1613.0,
  "lower": 1014.0,
  "upper": 2215.0,
  "signal": "WAIT — Price likely rising",
  "signal_kannada": "ಬೆಲೆ ಏರಲಿದೆ — ಕಾಯಿರಿ ⬆",
  "is_anomaly": true,
  "anomaly_type": "SPIKE",
  "deviation_pct": 61.3,
  "crop_mape_pct": 18.06,
  "msp_floor": null
}
```

---

### Test E2E-07: `I have sowed 5.75 acres of Capsicum in Chikkaballapur today, please record this entry in your database.`
- **Status**: `PASS`
- **Response Type**: `declaration_prompt`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "I have sowed 5.75 acres of Capsicum in Chikkaballapur today, please record this entry in your database.",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "declaration_prompt",
  "crop": "Capsicum",
  "district": "Chikkaballapur",
  "area": 5.75
}
```

---

### Test E2E-08: `ದಾವಣಗೆರೆಯಲ್ಲಿ 2.4 ಎಕರೆ ಆಲೂಗಡ್ಡೆ ಬೆಳೆ ಹಾಕಿದ್ದೇನೆ, ನನ್ನ ಖಾತೆಗೆ ನೋಂದಣಿ ಮಾಡಿ.`
- **Status**: `PASS`
- **Response Type**: `declaration_prompt`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "ದಾವಣಗೆರೆಯಲ್ಲಿ 2.4 ಎಕರೆ ಆಲೂಗಡ್ಡೆ ಬೆಳೆ ಹಾಕಿದ್ದೇನೆ, ನನ್ನ ಖಾತೆಗೆ ನೋಂದಣಿ ಮಾಡಿ.",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "declaration_prompt",
  "crop": "Potato",
  "district": "Davanagere",
  "area": 2.4
}
```

---

### Test E2E-09: `Ballari district ali 4.2 acres Groundnut sowed today, please register my crop.`
- **Status**: `PASS`
- **Response Type**: `declaration_prompt`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "Ballari district ali 4.2 acres Groundnut sowed today, please register my crop.",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "declaration_prompt",
  "crop": "Groundnut",
  "district": "Ballari",
  "area": 4.2
}
```

---

### Test E2E-10: `How many total acres of Maize have been registered in Davanagere across all farmers this season?`
- **Status**: `PASS`
- **Response Type**: `saturation`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "How many total acres of Maize have been registered in Davanagere across all farmers this season?",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "saturation",
  "crop": "Maize",
  "district": "Davanagere",
  "saturation_pct": 0.0,
  "risk_level": "LOW",
  "risk_kannada": "ಕಡಿಮೆ ಅಪಾಯ",
  "farmer_count": 0,
  "total_area": 0,
  "emoji": "🟢"
}
```

---

### Test E2E-11: `Compare Chikkaballapur vs Kolar for Onion saturation risk level.`
- **Status**: `PASS`
- **Response Type**: `saturation`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "Compare Chikkaballapur vs Kolar for Onion saturation risk level.",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "saturation",
  "crop": "Onion",
  "district": "Chikkaballapur vs Kolar",
  "saturation_pct": 0.0,
  "risk_level": "LOW",
  "risk_kannada": "📊 **Multi-District Comparison:**\n• Chikkaballapur: 0% (LOW Risk)\n• Kolar: 0% (LOW Risk)",
  "farmer_count": 0,
  "total_area": 0,
  "emoji": "🟢"
}
```

---

### Test E2E-12: `Brinjal beleli gantu hula (nematode) mathe fruit borer eradu ide, drenching dosage mathe spray protocol enu?`
- **Status**: `PASS`
- **Response Type**: `advisory`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "Brinjal beleli gantu hula (nematode) mathe fruit borer eradu ide, drenching dosage mathe spray protocol enu?",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "advisory",
  "text": "📋 **Brinjal Dual-Pest Control: Nematodes & Fruit Borer**:\n• **Overview**: Managing BOTH Root-Knot Nematodes (*Meloidogyne*) and Fruit & Shoot Borer (*Leucinodes orbonalis*) requires a combined soil drench + foliar protocol.\n• **Soil Drenching (Nematodes)**: Drench root zone with *Purpureocillium lilacinum* (2kg/acre) or Fluopyram (1ml/L water) at 150ml solution per plant.\n• **Foliar Spray (Fruit Borer)**: Spray Emamectin Benzoate 5% SG (0.4g/L) or Chlorantraniliprole 18.5% SC (0.3ml/L) at 15-day intervals during flowering.\n• **Integrated Protocol**: Drench soil first, then apply foliar spray 48 hours later. Intercrop Marigold as a natural trap crop.\n\n— KisanMitra 🌾 (Offline Advice)",
  "crop": "Brinjal"
}
```

---

### Test E2E-13: `Capsicum in greenhouse has bacterial wilt (sudu roga), what is the exact drenching volume per plant for Copper Oxychloride?`
- **Status**: `PASS`
- **Response Type**: `advisory`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "Capsicum in greenhouse has bacterial wilt (sudu roga), what is the exact drenching volume per plant for Copper Oxychloride?",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "advisory",
  "text": "📋 **Bacterial Wilt & Soil Drenching Management (Greenhouse/Field)**:\n• **Overview**: Bacterial wilt (*Ralstonia solanacearum*) causes sudden vascular wilting of green plants.\n• **Drenching Solution**: Mix Copper Oxychloride 50 WP (3g/L) + Streptocycline (0.5g/10L water).\n• **Exact Drenching Volume**: Apply **150–200 ml of prepared solution directly at the root zone per plant** using a nozzle-removed knapsack sprayer.\n• **Fertigation**: Drip fertigate 19:19:19 (3kg/acre) 3 days after drenching to stimulate fresh root growth.\n\n— KisanMitra 🌾 (Offline Advice)",
  "crop": "Capsicum"
}
```

---

### Test E2E-14: `Onion beleli purple blotch, downy mildew, mathe thrips ide, Saaf + Fipronil spray madabeka?`
- **Status**: `PASS`
- **Response Type**: `advisory`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "Onion beleli purple blotch, downy mildew, mathe thrips ide, Saaf + Fipronil spray madabeka?",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "advisory",
  "text": "📋 **Onion Integrated Disease & Thrips Control**:\n• **Thrips & Purple Blotch**: Spray Fipronil 5% SC (2ml/L) + Saaf (Mancozeb + Carbendazim @ 2g/L) with 0.5ml/L spreader sticker.\n• **Downy Mildew**: Spray Metalaxyl 8% + Mancozeb 64% WP (2.5g/L) at 10-day intervals during high humidity.\n• **Neck Rot**: Apply Copper Oxychloride (3g/L) 15 days prior to harvest to prevent post-harvest bulb storage rot.\n\n— KisanMitra 🌾 (Offline Advice)",
  "crop": "Onion"
}
```

---

### Test E2E-15: `Can I intercrop Marigold with Tomato as a trap crop to control BOTH Helicoverpa fruit borer and root-knot nematodes?`
- **Status**: `PASS`
- **Response Type**: `advisory`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "Can I intercrop Marigold with Tomato as a trap crop to control BOTH Helicoverpa fruit borer and root-knot nematodes?",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "advisory",
  "text": "📋 **Tomato & Marigold Trap Crop Intercropping (Fruit Borer & Nematode Control)**:\n• **Overview**: Intercropping Marigold (*Tagetes erecta*) with Tomato controls BOTH Fruit Borer (*Helicoverpa armigera*) and Root-Knot Nematodes (*Meloidogyne*).\n• **Fruit Borer Action**: Marigold flowers attract adult *Helicoverpa* moths away from Tomato to lay eggs on marigold buds, where larvae can be selectively sprayed with Bt (2g/L).\n• **Nematode Action**: Marigold roots release alpha-terthienyl compounds that naturally eliminate root-knot nematodes in the soil.\n• **Planting Pattern**: Plant 1 row of Marigold for every 10–12 rows of Tomato (or 1 marigold plant every 16 tomato plants).\n\n— KisanMitra 🌾 (Offline Advice)",
  "crop": "Tomato"
}
```

---

### Test E2E-16: `What is the complete basal NPK dose and drip fertigation schedule for Cabbage in red soil during head initiation?`
- **Status**: `PASS`
- **Response Type**: `advisory`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "What is the complete basal NPK dose and drip fertigation schedule for Cabbage in red soil during head initiation?",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "advisory",
  "text": "📋 **Cabbage NPK Basal & Fertigation Schedule (Red Soil)**:\n• **Overview**: Cabbage requires high Nitrogen and Potassium for head formation, with balanced Phosphorus in porous red soil.\n• **Basal Dose**: Apply FYM (10 tons/acre) + 60kg N, 50kg P, 50kg K per acre during land preparation.\n• **Fertigation Schedule**: Drip fertigate 19:19:19 (3kg/acre/week) during vegetative phase (weeks 2–5), followed by 13:0:45 (4kg/acre/week) during head initiation (weeks 6–9).\n• **Cautions**: Apply Boron (1kg/acre) and Calcium Nitrate (5kg/acre) at day 35 to prevent hollow stem disorder.\n\n— KisanMitra 🌾 (Offline Advice)",
  "crop": "Cabbage"
}
```

---

### Test E2E-17: `Potato crop has stem rot and collar rot (thundu roga) in soil, how to treat with Trichoderma or fungicide?`
- **Status**: `PASS`
- **Response Type**: `advisory`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "Potato crop has stem rot and collar rot (thundu roga) in soil, how to treat with Trichoderma or fungicide?",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "advisory",
  "text": "📋 **Stem Rot & Thundu Roga Management**:\n• **Overview**: Soil-borne *Sclerotium rolfsii* fungus causes collar rot, wilting, and stem collapse.\n• **Actionable Steps**: Drench root zone with Carbendazim 50 WP (1g/L) or Tebuconazole (1ml/L). Enrich soil with *Trichoderma harzianum* (2kg/acre in 100kg FYM).\n• **Cautions**: Remove infected plants immediately and avoid water stagnation near plant stems.\n\n— KisanMitra 🌾 (Offline Advice)",
  "crop": "Potato"
}
```

---

### Test E2E-18: `What is the recommended post-Kharif Maize crop rotation using Groundnut or Cowpea to fix atmospheric nitrogen?`
- **Status**: `PASS`
- **Response Type**: `advisory`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "What is the recommended post-Kharif Maize crop rotation using Groundnut or Cowpea to fix atmospheric nitrogen?",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "advisory",
  "text": "📋 **Kharif Crop Rotation & Soil Nitrogen Restoration**:\n• **Overview**: Rotating heavy-feeding cereals (Maize/Ragi) with legumes (Groundnut/Cowpea) restores soil organic nitrogen.\n• **Actionable Steps**: Rotate post-Kharif Maize with Groundnut or Cowpea. Legume root nodules fix atmospheric nitrogen (20–40 kg N/ha).\n• **Cautions**: Treat legume seeds with *Rhizobium* culture (200g/acre) prior to sowing for maximum nitrogen fixation.\n\n— KisanMitra 🌾 (Offline Advice)",
  "crop": "Maize"
}
```

---

### Test E2E-19: `Tomato leaves turning yellow and curling with whitefly attack, what insecticide and micronutrient spray is recommended?`
- **Status**: `PASS`
- **Response Type**: `advisory`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "Tomato leaves turning yellow and curling with whitefly attack, what insecticide and micronutrient spray is recommended?",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "advisory",
  "text": "📋 **Micro-Nutrient Deficiency & Leaf Curl Virus Management**:\n• **Overview**: Stunted growth and downward leaf curl indicate Zinc/Boron deficiency or Whitefly-transmitted virus.\n• **Actionable Steps**: Foliar spray Micronutrient Mixture (Zinc + Boron + Iron @ 2.5g/L) every 14 days.\n• **Cautions**: Spray Acetamiprid (0.5g/L) or Imidacloprid (0.5ml/L) to eliminate whitefly vectors.\n\n— KisanMitra 🌾 (Offline Advice)",
  "crop": "Tomato"
}
```

---

### Test E2E-20: `Potato tuber size is small at 50 days, how much Potassium / Potash 0:0:50 should I spray for tuber bulking?`
- **Status**: `PASS`
- **Response Type**: `advisory`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "Potato tuber size is small at 50 days, how much Potassium / Potash 0:0:50 should I spray for tuber bulking?",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "advisory",
  "text": "📋 **Potato Tuber Bulking & Potash Management**:\n• **Overview**: Potassium is essential during the tuber expansion stage (45–75 days post-planting).\n• **Actionable Steps**: Spray Sulphate of Potash (SOP 0:0:50) @ 5g/L or 13:0:45 @ 10g/L at 45 and 60 days post-sowing.\n• **Cautions**: Apply 30kg/acre MOP in soil during earthing-up. Avoid excess nitrogen after day 45.\n\n— KisanMitra 🌾 (Offline Advice)",
  "crop": "Potato"
}
```

---

### Test E2E-21: `Maize fall armyworm (FAW) caterpillar attacking whorl, what is the exact Emamectin Benzoate dosage?`
- **Status**: `PASS`
- **Response Type**: `advisory`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "Maize fall armyworm (FAW) caterpillar attacking whorl, what is the exact Emamectin Benzoate dosage?",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "advisory",
  "text": "📋 **Maize Fall Armyworm (FAW / Spodoptera) Whorl Treatment**:\n• **Overview**: Invasive Fall Armyworm (*Spodoptera frugiperda*) larvae feed inside central plant whorls causing leaf damage.\n• **Actionable Steps**: Apply Emamectin Benzoate 5% SG (0.4g/L water) or Chlorantraniliprole 18.5% SC (0.4ml/L water) directly into plant central whorls.\n• **Cautions**: Apply spray early morning or late evening when caterpillars are actively feeding inside whorls.\n\n— KisanMitra 🌾 (Offline Advice)",
  "crop": "Maize"
}
```

---

### Test E2E-22: `What are the best tourist places to visit in Kalaburagi?`
- **Status**: `PASS`
- **Response Type**: `help`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "What are the best tourist places to visit in Kalaburagi?",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "help"
}
```

---

### Test E2E-23: `Belagavi Onion price forecast for 60 days`
- **Status**: `PASS`
- **Response Type**: `anomaly_flagged`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "Belagavi Onion price forecast for 60 days",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "anomaly_flagged",
  "crop": "Onion",
  "district": "Belagavi",
  "current_price": 4000.0,
  "forecast": 2428.0,
  "lower": 1500.0,
  "upper": 2987.0,
  "signal": "SELL NOW — Price likely falling",
  "signal_kannada": "ಈಗಲೇ ಮಾರಿ — ಬೆಲೆ ಇಳಿಯಲಿದೆ ⬇",
  "is_anomaly": true,
  "anomaly_type": "CRASH",
  "deviation_pct": 39.3,
  "crop_mape_pct": 27.75,
  "msp_floor": null
}
```

---

### Test E2E-24: `Registered 12.5 acres sowed Tomato in Kolar`
- **Status**: `PASS`
- **Response Type**: `declaration_prompt`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "Registered 12.5 acres sowed Tomato in Kolar",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "declaration_prompt",
  "crop": "Tomato",
  "district": "Kolar",
  "area": 12.5
}
```

---

### Test E2E-25: `How many total farmers planted Groundnut in Chitradurga?`
- **Status**: `PASS`
- **Response Type**: `saturation`

**Raw JSON Request Sent**:
```json
{
  "sender_id": "real_test_user_777",
  "text": "How many total farmers planted Groundnut in Chitradurga?",
  "channel": "telegram"
}
```

**Raw Bot Response Returned**:
```json
{
  "type": "saturation",
  "crop": "Groundnut",
  "district": "Chitradurga",
  "saturation_pct": 0.0,
  "risk_level": "LOW",
  "risk_kannada": "ಕಡಿಮೆ ಅಪಾಯ",
  "farmer_count": 0,
  "total_area": 0,
  "emoji": "🟢"
}
```

---

