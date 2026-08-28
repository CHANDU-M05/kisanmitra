// src/pages/AdvisoryView.jsx
import React, { useState } from 'react';
import { MessageSquare, Send, Sparkles, HelpCircle, CheckCircle, Mic } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { useTranslation } from 'react-i18next';
import Card from '../components/ui/Card';

import { API } from '../config';

export default function AdvisoryView() {
  const [selectedCrop, setSelectedCrop] = useState('Tomato');
  const [query, setQuery] = useState('');
  const [response, setResponse] = useState('');
  const [loading, setLoading] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [messageId, setMessageId] = useState(null);
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);
  
  const { t, i18n } = useTranslation();

  const getSampleQueries = () => {
    const isEn = i18n.language === 'en';
    switch (selectedCrop) {
      case 'Tomato':
        return [
          { text: isEn ? "How to protect Tomato from fruit rot in heavy rain?" : "ಮಳೆಯಲ್ಲಿ ಟೊಮೆಟೊ ಹೂ ಮತ್ತು ಕಾಯಿ ಕೊಳೆಯದಂತೆ ತಡೆಯುವುದು ಹೇಗೆ?", crop: "Tomato" },
          { text: isEn ? "What is the best fertilizer dose for Tomato?" : "ಟೊಮೆಟೊ ಬೆಳೆಗೆ ಯಾವ ಗೊಬ್ಬರ ಎಷ್ಟು ಪ್ರಮಾಣದಲ್ಲಿ ಹಾಕಬೇಕು?", crop: "Tomato" },
          { text: isEn ? "How to control late blight in Tomato?" : "ಟೊಮೆಟೊ ಬೆಳೆಗೆ ಬರುವ ಅಂಗಮಾರಿ ರೋಗ ನಿಯಂತ್ರಣ ಹೇಗೆ?", crop: "Tomato" }
        ];
      case 'Maize':
        return [
          { text: isEn ? "How to control Fall Armyworm pest in Maize?" : "ಮೆಕ್ಕೆಜೋಳದ ಕತ್ತರಿಸುಳ್ಳು/ಸೈನಿಕ ಹುಳು ಬಾಧೆ ತಡೆಯುವುದು ಹೇಗೆ?", crop: "Maize" },
          { text: isEn ? "When should I apply urea fertilizer to Maize?" : "ಮೆಕ್ಕೆಜೋಳಕ್ಕೆ ಯೂರಿಯಾ ಗೊಬ್ಬರವನ್ನು ಯಾವಾಗ ನೀಡಬೇಕು?", crop: "Maize" },
          { text: isEn ? "What is the optimal irrigation schedule for Maize?" : "ಮೆಕ್ಕೆಜೋಳದ ಬೆಳೆಗೆ ನೀರಿನ ನಿರ್ವಹಣೆ ಹೇಗೆ ಮಾಡಬೇಕು?", crop: "Maize" }
        ];
      case 'Onion':
        return [
          { text: isEn ? "How to treat purple blotch and bulb rot in Onion?" : "ಈರುಳ್ಳಿ ಕೊಳೆರೋಗ ಮತ್ತು ತಿರುಗು ರೋಗಕ್ಕೆ ಸೂಕ್ತ ಚಿಕಿತ್ಸೆ ಏನು?", crop: "Onion" },
          { text: isEn ? "Which nutrients help increase Onion bulb size?" : "ಈರುಳ್ಳಿ ದಪ್ಪಗಾಗಲು ಯಾವ ಪೋಷಕಾಂಶಗಳನ್ನು ಬಳಸಬೇಕು?", crop: "Onion" },
          { text: isEn ? "What is the recommended seed rate for Onion planting?" : "ಒಂದು ಎಕರೆ ಈರುಳ್ಳಿ ಸಸ್ಯ ನಾಟಿಗೆ ಎಷ್ಟು ಬೀಜ ಬೇಕಾಗುತ್ತದೆ?", crop: "Onion" }
        ];
      case 'Ragi':
        return [
          { text: isEn ? "How to prevent blast disease in Ragi crop?" : "ರಾಗಿ ಬೆಳೆಗೆ ಬರುವ ಕುತ್ತಿಗೆ ಕೊಳೆ ಮತ್ತು ಎಲೆ ಕರಕು ರೋಗ ತಡೆಯುವುದು ಹೇಗೆ?", crop: "Ragi" },
          { text: isEn ? "What is the best harvesting time for Ragi?" : "ರಾಗಿ ಬೆಳೆ ಕಟಾವು ಮಾಡಲು ಸರಿಯಾದ ಸಮಯ ಯಾವುದು?", crop: "Ragi" },
          { text: isEn ? "How can I improve my Ragi grain yield per acre?" : "ರಾಗಿ ಬೆಳೆಯಲ್ಲಿ ಹೆಚ್ಚಿನ ತೆನೆ ಮತ್ತು ಇಳುವರಿ ಪಡೆಯುವುದು ಹೇಗೆ?", crop: "Ragi" }
        ];
      case 'Potato':
        return [
          { text: isEn ? "How to treat late blight disease in Potato?" : "ಆಲೂಗಡ್ಡೆ ಬೆಳೆಗೆ ಬರುವ ಲೇಟ್ ಬ್ಲೈಟ್ ರೋಗ ನಿಯಂತ್ರಣ ಹೇಗೆ?", crop: "Potato" },
          { text: isEn ? "What is the correct spacing for planting Potato tubers?" : "ಆಲೂಗಡ್ಡೆ ನಾಟಿ ಮಾಡಲು ಸಾಲುಗಳ ನಡುವೆ ಎಷ್ಟು ಅಂತರವಿರಬೇಕು?", crop: "Potato" },
          { text: isEn ? "When should I stop watering Potato before harvest?" : "ಆಲೂಗಡ್ಡೆ ಕಟಾವಿಗೆ ಮುನ್ನ ಕೊನೆಯ ನೀರಾವರಿ ಯಾವಾಗ ನಿಲ್ಲಿಸಬೇಕು?", crop: "Potato" }
        ];
      case 'Brinjal':
        return [
          { text: isEn ? "How to control shoot and fruit borer in Brinjal?" : "ಬದನೆಕಾಯಿಯ ಕಾಂಡ ಮತ್ತು ಕಾಯಿ ಕೊರಕ ಕೀಟ ನಿಯಂತ್ರಿಸುವುದು ಹೇಗೆ?", crop: "Brinjal" },
          { text: isEn ? "What is the optimal fertilizer dose for Brinjal?" : "ಬದನೆ ಬೆಳೆಗೆ ಎಷ್ಟು ಪ್ರಮಾಣದಲ್ಲಿ ರಸಗೊಬ್ಬರ ನೀಡಬೇಕು?", crop: "Brinjal" },
          { text: isEn ? "How to manage little leaf disease in Brinjal?" : "ಬದನೆ ಬೆಳೆಯಲ್ಲಿ ನುಸಿ ರೋಗ ಮತ್ತು ಸಣ್ಣ ಎಲೆ ರೋಗ ನಿಯಂತ್ರಣ ಹೇಗೆ?", crop: "Brinjal" }
        ];
      case 'Marigold':
        return [
          { text: isEn ? "How to manage leaf spot and bud rot in Marigold?" : "ಚೆಂಡುಹೂವಿನ ಎಲೆ ಚುಕ್ಕೆ ಮತ್ತು ಮೊಗ್ಗು ಕೊಳೆ ರೋಗ ತಡೆಯುವುದು ಹೇಗೆ?", crop: "Marigold" },
          { text: isEn ? "What is the recommended plant spacing for Marigold?" : "ಚೆಂಡುಹೂ ನಾಟಿ ಮಾಡಲು ಗಿಡಗಳ ನಡುವೆ ಎಷ್ಟು ಅಂತರವಿರಬೇಕು?", crop: "Marigold" },
          { text: isEn ? "Which nutrients help increase Marigold flower yield?" : "ಚೆಂಡುಹೂವಿನಲ್ಲಿ ಹೆಚ್ಚು ಮೊಗ್ಗು ಮತ್ತು ಇಳುವರಿ ಪಡೆಯಲು ಯಾವ ಪೋಷಕಾಂಶ ಬಳಸಬೇಕು?", crop: "Marigold" }
        ];
      default:
        return [
          { text: isEn ? `What is the optimal fertilizer for ${selectedCrop}?` : `${selectedCrop} ಬೆಳೆಗೆ ಸೂಕ್ತ ಗೊಬ್ಬರ ಯಾವುದು?`, crop: selectedCrop },
          { text: isEn ? `How to manage pests and diseases in ${selectedCrop}?` : `${selectedCrop} ಬೆಳೆಯಲ್ಲಿ ರೋಗ ಮತ್ತು ಕೀಟ ನಿರ್ವಹಣೆ ಹೇಗೆ?`, crop: selectedCrop },
          { text: isEn ? `What are the watering stages for ${selectedCrop}?` : `${selectedCrop} ಬೆಳೆಗೆ ಎಷ್ಟು ಬಾರಿ ನೀರು ಉಣಿಸಬೇಕು?`, crop: selectedCrop }
        ];
    }
  };

  const sampleQueries = getSampleQueries();

  const handleQuerySubmit = (e) => {
    if (e) e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setResponse('');
    setMessageId(null);
    setFeedbackSubmitted(false);

    fetch(`${API}/farmer/advisory`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: query,
        crop: selectedCrop
      })
    })
      .then(res => res.json())
      .then(data => {
        setResponse(data.response || 'No advice returned.');
        setMessageId(data.id || null);
        setLoading(false);
      })
      .catch(err => {
        console.error("RAG Query failed", err);
        setResponse("ಕ್ಷಮಿಸಿ, ಸರ್ವರ್ ತೊಂದರೆಯಿಂದ ಕೃಷಿ ಸಲಹೆ ಪಡೆಯಲು ಸಾಧ್ಯವಾಗುತ್ತಿಲ್ಲ. ದಯವಿಟ್ಟು ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.");
        setLoading(false);
      });
  };

  const submitFeedback = (score) => {
    if (!messageId) return;
    fetch(`${API}/farmer/advisory/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message_id: messageId,
        score: score
      })
    })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          setFeedbackSubmitted(true);
          toast.success('Thank you for your feedback!');
        }
      })
      .catch(err => {
        console.error("Error submitting feedback", err);
        toast.error("Could not submit feedback.");
      });
  };

  const handleSampleClick = (sample) => {
    setSelectedCrop(sample.crop);
    setQuery(sample.text);
  };

  const handleVoiceInput = () => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      toast.error('Voice input is not supported in this browser.');
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = 'kn-IN';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      setIsListening(true);
      toast('Listening...', { icon: '🎤', duration: 3000 });
    };

    recognition.onresult = (event) => {
      const speechResult = event.results[0][0].transcript;
      setQuery(prev => prev ? prev + ' ' + speechResult : speechResult);
      toast.success('Audio captured!');
    };

    recognition.onerror = (event) => {
      console.error('Speech recognition error', event.error);
      toast.error('Could not capture audio. Please try again.');
      setIsListening(false);
    };

    recognition.onend = () => {
      setIsListening(false);
    };

    recognition.start();
  };

  return (
    <div className="space-y-6">
      {/* Top Banner Control deck */}
      <Card className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div className="space-y-1">
          <h2 className="text-sm font-bold uppercase tracking-wider flex items-center gap-2 text-slate-900 dark:text-white">
            <Sparkles className="h-4 w-4 text-emerald-500" /> {t('advisory.title')}
          </h2>
          <p className="text-xs text-slate-600">
            {t('advisory.subtitle')}
          </p>
        </div>
      </Card>

      {/* Main split layout */}
      <div className="grid grid-cols-1 lg:grid-cols-10 gap-6">
        
        {/* Left: Input Console (4 col) */}
        <Card className="lg:col-span-4 flex flex-col justify-between min-h-[350px]">
          <form onSubmit={handleQuerySubmit} className="space-y-4 flex-1">
            <div className="border-b border-slate-100 dark:border-white/5 pb-3 mb-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-white flex items-center gap-1.5">
                Ask a Question
              </h3>
            </div>

            {/* Crop Select */}
            <div className="space-y-1.5">
              <label className="text-[10px] font-bold text-slate-700 uppercase tracking-wider block">Target Crop</label>
              <select
                value={selectedCrop}
                onChange={(e) => setSelectedCrop(e.target.value)}
                className="w-full bg-white border border-slate-200 p-2.5 text-xs font-bold text-slate-800 focus:outline-none focus:border-slate-400 rounded-xl cursor-pointer dark:bg-slate-900/60 dark:border-white/10 dark:text-slate-200"
              >
                <option value="Tomato">TOMATO / ಟೊಮೆಟೊ</option>
                <option value="Maize">MAIZE / ಮೆಕ್ಕೆಜೋಳ</option>
                <option value="Onion">ONION / ಈರುಳ್ಳಿ</option>
                <option value="Potato">POTATO / ಆಲೂಗಡ್ಡೆ</option>
                <option value="Ragi">RAGI / ರಾಗಿ</option>
                <option value="Brinjal">BRINJAL / ಬದನೆಕಾಯಿ</option>
                <option value="Marigold">MARIGOLD / ಚೆಂಡುಹೂ</option>
              </select>
            </div>

            {/* Question Area */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <label className="text-[10px] font-bold text-slate-700 uppercase tracking-wider block">Your Question</label>
                  <span className="text-[8px] font-bold text-slate-400 dark:text-slate-550 uppercase tracking-wider">Kannada & English Supported</span>
                </div>
                <button
                  type="button"
                  onClick={handleVoiceInput}
                  disabled={isListening}
                  className={`p-1.5 rounded-lg border transition-colors flex items-center gap-1 text-[9px] font-bold uppercase ${
                    isListening 
                      ? 'bg-red-50 border-red-200 text-red-600 animate-pulse' 
                      : 'bg-white border-slate-200 text-slate-500 hover:bg-slate-50 dark:bg-slate-800 dark:border-white/10 dark:text-slate-400 dark:hover:bg-slate-700'
                  }`}
                  title="Use Voice Input"
                >
                  <Mic className="h-3 w-3" /> {isListening ? t('advisory.micActive') : t('advisory.micLabel')}
                </button>
              </div>
              <textarea
                placeholder={t('advisory.placeholder')}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                required
                rows="4"
                className="w-full bg-white border border-slate-200 rounded-xl p-3 text-xs placeholder-slate-400 focus:outline-none focus:border-emerald-500 transition-all font-medium resize-none leading-relaxed dark:bg-slate-900/60 dark:border-white/10 dark:text-white"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-emerald-500 hover:bg-emerald-600 disabled:bg-slate-300 text-slate-950 text-xs font-black py-3 rounded-xl uppercase tracking-wider shadow-lg shadow-emerald-500/10 flex items-center justify-center gap-2 transition-all mt-4"
            >
              {loading ? (
                <span>{t('advisory.botTyping')}</span>
              ) : (
                <>
                  <Send className="h-3.5 w-3.5" />
                  <span>{t('advisory.askBtn')}</span>
                </>
              )}
            </button>
          </form>

          {/* Quick template suggestions */}
          <div className="border-t border-slate-100 dark:border-white/5 pt-4 mt-4 space-y-2">
            <span className="text-[10px] font-bold text-slate-700 dark:text-slate-400 uppercase tracking-wider flex items-center gap-1">
              <HelpCircle className="h-3.5 w-3.5 text-slate-600" /> Recommended Questions
            </span>
            <div className="space-y-1.5">
              {sampleQueries.map((sample, idx) => (
                <button
                  key={idx}
                  onClick={() => handleSampleClick(sample)}
                  className="w-full text-left bg-slate-50 hover:bg-slate-100/80 border border-slate-200/60 p-2.5 rounded-xl text-[10px] font-medium text-slate-600 dark:bg-white/5 dark:border-white/10 dark:text-slate-350 dark:hover:bg-white/10 transition-colors"
                >
                  {sample.text}
                </button>
              ))}
            </div>
          </div>
        </Card>

        {/* Right: Response Display Panel (6 col) */}
        <Card className="lg:col-span-6 flex flex-col justify-between h-[520px] lg:h-auto">
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-800 dark:text-white flex items-center gap-1.5 border-b border-slate-100 dark:border-white/5 pb-3 mb-4 shrink-0">
            <MessageSquare className="h-4 w-4 text-emerald-500" /> Agronomy Advisory Report
          </h3>

          <div className="flex-1 overflow-y-auto pr-2">
            {loading ? (
              <div className="h-full flex flex-col items-center justify-center space-y-3 text-slate-600">
                <div className="h-7 w-7 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin"></div>
                <span className="text-xs font-bold animate-pulse uppercase tracking-wider font-mono">Analyzing context files via Gemini...</span>
              </div>
            ) : response ? (
              <div className="space-y-4">
                <div className="leading-relaxed text-sm text-slate-950 bg-emerald-50/15 border border-emerald-200/50 p-5 rounded-2xl shadow-inner font-sans whitespace-pre-wrap animate-fade-in">
                  {response}
                </div>
                
                {/* Feedback Panel */}
                {messageId && (
                  <div className="mt-4 pt-3 border-t border-slate-100 dark:border-white/5 flex items-center justify-between">
                    <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Was this advice helpful?</span>
                    {feedbackSubmitted ? (
                      <span className="text-[10px] font-bold text-emerald-600 dark:text-emerald-400">Feedback registered. Thank you!</span>
                    ) : (
                      <div className="flex gap-2">
                        <button
                          onClick={() => submitFeedback(1)}
                          className="px-3 py-1 border border-slate-200 hover:border-emerald-500 hover:bg-emerald-50 hover:text-emerald-700 dark:border-white/10 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-emerald-500/10 dark:hover:text-emerald-400 rounded-lg text-[10px] font-bold uppercase transition-all flex items-center gap-1 cursor-pointer"
                        >
                          👍 Helpful
                        </button>
                        <button
                          onClick={() => submitFeedback(-1)}
                          className="px-3 py-1 border border-slate-200 hover:border-red-500 hover:bg-red-50 hover:text-red-700 dark:border-white/10 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-red-500/10 dark:hover:text-red-400 rounded-lg text-[10px] font-bold uppercase transition-all flex items-center gap-1 cursor-pointer"
                        >
                          👎 Not Helpful
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-center space-y-2 p-6">
                <MessageSquare className="h-8 w-8 text-slate-400" />
                <h4 className="text-xs font-bold text-slate-700 uppercase tracking-wider">No active query session</h4>
                <p className="text-[11px] text-slate-600 max-w-xs">
                  Fill in a question in the console on the left or select a template to load immediate agronomist guidance.
                </p>
              </div>
            )}
          </div>

          <div className="bg-slate-50 border-t border-slate-200 dark:bg-white/[0.02] dark:border-white/5 p-3.5 text-[10px] font-mono font-bold text-slate-600 dark:text-slate-500 flex items-center gap-2 rounded-b-xl shrink-0 mt-4">
            <CheckCircle className="h-3.5 w-3.5 text-emerald-500" />
            <span>RESPONSES RESOLVE DYNAMICALLY FROM CANONICAL AGRONOMY KNOWLEDGE DATABASES.</span>
          </div>
        </Card>

      </div>
    </div>
  );
}
