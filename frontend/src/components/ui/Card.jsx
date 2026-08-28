import React from 'react';

const CARD_CLASS = "bg-white border border-slate-200 rounded-2xl p-5 shadow-sm dark:bg-white/5 dark:backdrop-blur-xl dark:border-white/10";

export default function Card({ className = '', children }) {
  return <div className={`${CARD_CLASS} ${className}`}>{children}</div>;
}
