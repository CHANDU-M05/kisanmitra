"""
Offline advisory fallback routing tests (pure function, no DB, no network).

Motivating incident 2026-10-27: a Kannada tomato fertiliser question
("ಟೊಮೆಟೊ ಬೆಳೆಗೆ ಯಾವ ಗೊಬ್ಬರ ಎಷ್ಟು ಪ್ರಮಾಣದಲ್ಲಿ ಹಾಕಬೇಕು?")
with crop=Tomato selected returned the MAIZE nutrition & fall armyworm
advisory. Root cause: the maize rule listed the crop-agnostic words
"ಗೊಬ್ಬರ" (fertilizer) / "ಯೂರಿಯಾ" / "dap" and sits BEFORE the tomato rule;
the tomato rule additionally only knew the spelling ಟೊಮ್ಯಾಟೊ, not the
widely typed ಟೊಮೆಟೊ.
"""
from backend.services.rag import get_offline_fallback

TOMATO_FERT_KN = "ಟೊಮೆಟೊ ಬೆಳೆಗೆ ಯಾವ ಗೊಬ್ಬರ ಎಷ್ಟು ಪ್ರಮಾಣದಲ್ಲಿ ಹಾಕಬೇಕು?"
MAIZE_KN = "ಮೆಕ್ಕೆಜೋಳದಲ್ಲಿ ಸೈನಿಕ ಹುಳು ನಿಯಂತ್ರಣ ಹೇಗೆ?"


def _msg(query, crop):
    return get_offline_fallback(query, crop)[0]


def test_kannada_tomato_fertiliser_not_answered_with_maize_advice():
    msg = _msg(TOMATO_FERT_KN, "Tomato")
    assert "ಮೆಕ್ಕೆಜೋಳ" not in msg, "crop-agnostic word 'ಗೊಬ್ಬರ' hijacked the maize rule"
    assert "ಟೊಮೆಟೊ" in msg or "ಟೊಮ್ಯಾಟೊ" in msg


def test_kannada_fertiliser_without_crop_never_returns_crop_specific_advice():
    msg = _msg("ಬೆಳೆಗೆ ಗೊಬ್ಬರ ಎಷ್ಟು ಹಾಕಬೇಕು?", None)
    # no crop context, no crop named in the query -> generic crop-care default
    assert "ಮೆಕ್ಕೆಜೋಳ ಪೋಷಕಾಂಶ" not in msg
    assert "ಆಲೂಗಡ್ಡೆ" not in msg


def test_maize_context_still_routes_to_maize_rule():
    msg = _msg(MAIZE_KN, "Maize")
    assert "ಸೈನಿಕ ಹುಳು" in msg and "ಮೆಕ್ಕೆಜೋಳ" in msg
    # and via in-query crop mention even without the crop parameter
    assert "ಮೆಕ್ಕೆಜೋಳ" in _msg(MAIZE_KN, None)


def test_generic_spray_word_does_not_force_wilt_answer():
    msg = _msg("ಟೊಮೆಟೊ ಬೆಳೆಗೆ ಯಾವಾಗ ಸಿಂಪಡಿಸಬೇಕು?", "Tomato")
    assert "ಬ್ಯಾಕ್ಟೀರಿಯಲ್ ವೈಲ್ಟ್" not in msg  # bare "spray-ish" is not a wilt signal


def test_english_phosphate_question_not_routed_to_alkaline_soil_rule():
    # "ph" used to be a substring test: "phosphate" matched the pH rule.
    msg = _msg("best phosphate fertiliser for tomato", "Tomato")
    assert "Alkaline Soil" not in msg


def test_english_subtropical_word_does_not_trigger_bt_rule():
    msg = _msg("is tomato suitable in subtropical climate", "Tomato")
    assert "Bt Bio-Pesticide" not in msg
