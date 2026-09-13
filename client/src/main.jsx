import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'

// Work Sans auto-hébergée : les fichiers de police sont servis par le bundle,
// aucune requête vers fonts.googleapis.com (§9.0 de SPEC-CRA.md).
import '@fontsource/work-sans/300.css'
import '@fontsource/work-sans/400.css'
import '@fontsource/work-sans/500.css'
import '@fontsource/work-sans/600.css'
import '@fontsource/work-sans/700.css'
import '@fontsource/work-sans/800.css'
import '@fontsource/work-sans/900.css'

import './theme.css'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
        <App />
    </React.StrictMode>,
)
