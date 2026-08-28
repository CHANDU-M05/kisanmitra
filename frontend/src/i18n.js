import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

const resources = {
  en: {
    translation: {
      advisory: {
        title: "AI Agronomist",
        subtitle: "Real-time crop advice and weather insights based on your district",
        placeholder: "Ask about fertilizers, weather, or crop diseases...",
        micLabel: "Hold to Speak",
        micActive: "Listening...",
        micError: "Microphone error",
        askBtn: "Ask Agronomist",
        sourcesLabel: "Knowledge Sources:",
        botTyping: "KisanMitra is thinking...",
        prompts: {
          q1: "What fertilizer for Tomato?",
          q2: "When to harvest Ragi?",
          q3: "Maize pest control"
        }
      },
      declare: {
        title: "Sowing Registration",
        subtitle: "Submit your crop plan to receive accurate market forecasting and advisory",
        farmerName: "Farmer Name",
        phone: "Phone Number",
        district: "District",
        crop: "Primary Crop",
        area: "Acreage",
        submitBtn: "Register Sowing Plan"
      }
    }
  },
  kn: {
    translation: {
      advisory: {
        title: "AI ಕೃಷಿ ಸಲಹೆಗಾರ",
        subtitle: "ನಿಮ್ಮ ಜಿಲ್ಲೆಯ ಆಧಾರದ ಮೇಲೆ ನೈಜ-ಸಮಯದ ಬೆಳೆ ಸಲಹೆ ಮತ್ತು ಹವಾಮಾನ ಮಾಹಿತಿ",
        placeholder: "ರಸಗೊಬ್ಬರಗಳು, ಹವಾಮಾನ, ಅಥವಾ ಬೆಳೆ ರೋಗಗಳ ಬಗ್ಗೆ ಕೇಳಿ...",
        micLabel: "ಮಾತನಾಡಲು ಒತ್ತಿ",
        micActive: "ಆಲಿಸುತ್ತಿದೆ...",
        micError: "ಮೈಕ್ರೊಫೋನ್ ದೋಷ",
        askBtn: "ಕೇಳಿ",
        sourcesLabel: "ಮಾಹಿತಿ ಮೂಲಗಳು:",
        botTyping: "ಕಿಸಾನ್ ಮಿತ್ರ ಯೋಚಿಸುತ್ತಿದೆ...",
        prompts: {
          q1: "ಟೊಮ್ಯಾಟೊಗೆ ಯಾವ ಗೊಬ್ಬರ?",
          q2: "ರಾಗಿ ಕಟಾವು ಯಾವಾಗ?",
          q3: "ಮೆಕ್ಕೆಜೋಳದ ಕೀಟ ನಿಯಂತ್ರಣ"
        }
      },
      declare: {
        title: "ಬಿತ್ತನೆ ನೋಂದಣಿ",
        subtitle: "ನಿಖರ ಮಾರುಕಟ್ಟೆ ಮುನ್ಸೂಚನೆ ಮತ್ತು ಸಲಹೆ ಪಡೆಯಲು ನಿಮ್ಮ ಬೆಳೆ ಯೋಜನೆಯನ್ನು ಸಲ್ಲಿಸಿ",
        farmerName: "ರೈತನ ಹೆಸರು",
        phone: "ಫೋನ್ ಸಂಖ್ಯೆ",
        district: "ಜಿಲ್ಲೆ",
        crop: "ಮುಖ್ಯ ಬೆಳೆ",
        area: "ಎಕರೆ",
        submitBtn: "ಬಿತ್ತನೆ ಯೋಜನೆ ನೋಂದಾಯಿಸಿ"
      }
    }
  }
};

i18n
  .use(initReactI18next)
  .init({
    resources,
    lng: "en", // default language
    fallbackLng: "en",
    interpolation: {
      escapeValue: false 
    }
  });

export default i18n;
