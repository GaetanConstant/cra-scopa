import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'node:fs'

// VERSION à la racine du dépôt est la source unique du numéro affiché
// (le package.json ne sert pas à l'affichage). L'année est figée au build :
// le build Docker se fait à chaque déploiement, c'est donc la dernière livraison.
const version = readFileSync(new URL('../VERSION', import.meta.url), 'utf-8').trim()

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(version),
    __APP_YEAR__: JSON.stringify(String(new Date().getFullYear())),
  },
})
