import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

const resources = {
  en: {
    translation: {
      nav: {
        command: "KM Command",
        farmer: "KM Farmer",
        terminal: "Market Prices",
        insights: "Saturation Index",
        agronomist: "AI Agronomist",
        climate: "Climate Forecast",
        sowing: "Register Sowing Plan",
        calendar: "Crop Calendar",
        farmers: "Farmers Registry",
        transcripts: "Bot Transcripts",
        settings: "System Settings",
        adminConsole: "Admin Console",
        terminateSession: "Terminate Session"
      },
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
      },
      weather: {
        title: "Climate & Sowing Window Forecast",
        subtitle: "Localized meteorological monitoring paired with real-time agronomic crop advice.",
        selectDistrict: "Select District:",
        temperature: "Temperature",
        humidity: "Humidity",
        rainProb: "Rain Probability",
        soilMoisture: "Soil Moisture"
      }
    }
  },
  kn: {
    translation: {
      nav: {
        command: "ಕಿಸಾನ್‌ಮಿತ್ರ ನಿಯಂತ್ರಣ",
        farmer: "ಕಿಸಾನ್‌ಮಿತ್ರ ರೈತ",
        terminal: "ಮಾರುಕಟ್ಟೆ ಬೆಲೆಗಳು",
        insights: "ಸ್ಯಾಚುರೇಶನ್ ಸೂಚ್ಯಂಕ",
        agronomist: "AI ಕೃಷಿ ಸಲಹೆಗಾರ",
        climate: "ಹವಾಮಾನ ಮುನ್ಸೂಚನೆ",
        sowing: "ಬಿತ್ತನೆ ನೋಂದಣಿ",
        calendar: "ಬೆಳೆ ಕ್ಯಾಲೆಂಡರ್",
        farmers: "ರೈತರ ನೋಂದಣಿ ಪಟ್ಟಿ",
        transcripts: "ಬಾಟ್ ಚಾಟ್ ಇತಿಹಾಸ",
        settings: "ಸಿಸ್ಟಮ್ ಸೆಟ್ಟಿಂಗ್‌ಗಳು",
        adminConsole: "ಅಡ್ಮಿನ್ ಕಾನ್ಸೋಲ್",
        terminateSession: "ಲಾಗ್‌ಔಟ್ ಮಾಡಿ"
      },
      advisory: {
        title: "AI ಕೃಷಿ ಸಲಹೆಗಾರ",
        subtitle: "ನಿಮ್ಮ ಜಿಲ್ಲೆಯ ಆಧಾರದ ಮೇಲೆ ನೈಜ-ಸಮಯದ ಬೆಳೆ ಸಲಹೆ ಮತ್ತು ಹವಾಮಾನ ಮಾಹಿತಿ",
        placeholder: "ರಸಗೊಬ್ಬರಗಳು, ಹವಾಮಾನ, ಅಥವಾ ಬೆಳೆ ರೋಗಗಳ ಬಗ್ಗೆ ಕೇಳಿ...",
        micLabel: "ಮಾತನಾಡಲು ಒತ್ತಿ",
        micActive: "ಆಲಿಸುತ್ತಿದೆ...",
        micError: "ಮೈಕ್ರೊಫೋನ್ ದೋಷ",
        askBtn: "ಸಲಹೆ ಪಡೆಯಿರಿ",
        sourcesLabel: "ಮಾಹಿತಿ ಮೂಲಗಳು:",
        botTyping: "ಕಿಸಾನ್‌ಮಿತ್ರ ಆಲೋಚಿಸುತ್ತಿದೆ...",
        prompts: {
          q1: "ಟೊಮೆಟೊಗೆ ಯಾವ ಗೊಬ್ಬರ ನೀಡಬೇಕು?",
          q2: "ರಾಗಿ ಕಟಾವು ಮಾಡುವುದು ಯಾವಾಗ?",
          q3: "ಮೆಕ್ಕೆಜೋಳದ ಸೈನಿಕ ಹುಳು ನಿಯಂತ್ರಣ ಹೇಗೆ?"
        }
      },
      declare: {
        title: "ಬಿತ್ತನೆ ಯೋಜನೆ ನೋಂದಣಿ",
        subtitle: "ನಿಖರ ಮಾರುಕಟ್ಟೆ ಮುನ್ಸೂಚನೆ ಮತ್ತು ಸಲಹೆ ಪಡೆಯಲು ನಿಮ್ಮ ಬೆಳೆ ಯೋಜನೆಯನ್ನು ಸಲ್ಲಿಸಿ",
        farmerName: "ರೈತನ ಹೆಸರು",
        phone: "ಫೋನ್ ಸಂಖ್ಯೆ",
        district: "ಜಿಲ್ಲೆ",
        crop: "ಮುಖ್ಯ ಬೆಳೆ",
        area: "ಎಕರೆ ಪ್ರಮಾನ",
        submitBtn: "ಬಿತ್ತನೆ ಯೋಜನೆ ನೋಂದಾಯಿಸಿ"
      },
      weather: {
        title: "ಹವಾಮಾನ ಮತ್ತು ಬಿತ್ತನೆ ಸಮಯದ ಮುನ್ಸೂಚನೆ",
        subtitle: "ಸ್ಥಳೀಯ ಹವಾಮಾನ ವರದಿ ಮತ್ತು ನೈಜ-ಸಮಯದ ಕೃಷಿ ಸಲಹೆಗಳು.",
        selectDistrict: "ಜಿಲ್ಲೆಯನ್ನು ಆಯ್ಕೆ ಮಾಡಿ:",
        temperature: "ತಾಪಮಾನ",
        humidity: "ತೇವಾಂಶ",
        rainProb: "ಮಳೆ ಸಾಧ್ಯತೆ",
        soilMoisture: "ಮಣ್ಣಿನ ತೇವಾಂಶ"
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
