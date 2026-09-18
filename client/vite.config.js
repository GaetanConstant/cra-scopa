import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'node:fs'

// Version lue dans package.json, année figée au build : le build Docker se
// fait à chaque déploiement, c'est donc l'année de la dernière livraison.
const { version } = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8'))

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(version),
    __APP_YEAR__: JSON.stringify(String(new Date().getFullYear())),
  },
})
