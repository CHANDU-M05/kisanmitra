import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.ico', 'apple-touch-icon.png', 'masked-icon.svg'],

      manifest: {
        name: 'KisanMitra - Smart Crop Planning',
        short_name: 'KisanMitra',
        description: 'AI-powered market intelligence for Karnataka farmers',
        theme_color: '#16a34a',
        background_color: '#ffffff',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/',
        icons: [
          { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,ico}'],
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.includes('/prices/history'),
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'price-history-cache',
              expiration: { maxEntries: 100, maxAgeSeconds: 60 * 60 * 24 }, // 1 day
            },
          },
          {
            urlPattern: ({ url }) => url.pathname.includes('/prices/predict'),
            handler: 'NetworkFirst',
            options: {
              cacheName: 'price-prediction-cache',
              networkTimeoutSeconds: 5,
              expiration: { maxEntries: 50, maxAgeSeconds: 60 * 60 * 6 }, // 6 hours — offline fallback only
              cacheableResponse: {
                statuses: [0, 200],
              },
            },
          },
          {
            urlPattern: ({ url }) => url.pathname.includes('/saturation'),
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'saturation-cache',
              expiration: { maxEntries: 50, maxAgeSeconds: 60 * 60 * 12 }, // 12 hours
              cacheableResponse: {
                statuses: [0, 200],
              },
            },
          },
        ],
      },
      devOptions: {
        enabled: true,
      },
    }),
  ],
  server: {
    port: 3000,
    strictPort: true,
  }
});
