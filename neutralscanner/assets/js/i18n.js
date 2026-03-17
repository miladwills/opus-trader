/**
 * Neutral Scanner Pro - Internationalization (i18n)
 * Language switching with RTL support
 */

/**
 * I18n class
 * Handles language loading, switching, and DOM updates
 */
class I18n {
    constructor() {
        this.currentLang = 'en';
        this.translations = {};
        this.storageKey = 'scanner_language';
        this.supportedLangs = ['en', 'ar'];
        this.rtlLangs = ['ar'];
    }

    /**
     * Initialize i18n system
     */
    async init() {
        // Load saved language preference
        try {
            const saved = localStorage.getItem(this.storageKey);
            if (saved && this.supportedLangs.includes(saved)) {
                this.currentLang = saved;
            }
        } catch (e) {
            console.error('Failed to load language preference:', e);
        }

        // Load translations
        await this.loadTranslations(this.currentLang);

        // Setup language toggle buttons
        this.setupLanguageToggle();
    }

    /**
     * Load translations for a language
     */
    async loadTranslations(lang) {
        try {
            const response = await fetch(`./assets/i18n/${lang}.json`);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            this.translations = await response.json();
            this.currentLang = lang;

            // Save preference
            try {
                localStorage.setItem(this.storageKey, lang);
            } catch (e) {}

            // Apply RTL if needed
            this.applyRTL();

            // Update DOM
            this.applyTranslations();

            // Update active language button
            this.updateLanguageButtons();

            // Dispatch event for dynamic content
            document.dispatchEvent(new CustomEvent('i18n:changed', {
                detail: { lang: this.currentLang }
            }));

            return true;
        } catch (e) {
            console.error('Failed to load translations:', e);
            return false;
        }
    }

    /**
     * Get translation by key (dot notation)
     */
    t(key, fallback = null) {
        const keys = key.split('.');
        let value = this.translations;

        for (const k of keys) {
            if (value && typeof value === 'object' && k in value) {
                value = value[k];
            } else {
                return fallback !== null ? fallback : key;
            }
        }

        return value !== undefined ? value : (fallback !== null ? fallback : key);
    }

    /**
     * Apply RTL direction based on current language
     */
    applyRTL() {
        const html = document.documentElement;
        const isRTL = this.rtlLangs.includes(this.currentLang);

        if (isRTL) {
            html.setAttribute('dir', 'rtl');
            html.setAttribute('lang', this.currentLang);
            document.body.classList.add('rtl');
        } else {
            html.setAttribute('dir', 'ltr');
            html.setAttribute('lang', this.currentLang);
            document.body.classList.remove('rtl');
        }
    }

    /**
     * Apply translations to DOM elements
     */
    applyTranslations() {
        // Update elements with data-i18n attribute
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            const translation = this.t(key);
            if (translation && translation !== key) {
                el.textContent = translation;
            }
        });

        // Update placeholders with data-i18n-placeholder
        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            const key = el.getAttribute('data-i18n-placeholder');
            const translation = this.t(key);
            if (translation && translation !== key) {
                el.placeholder = translation;
            }
        });

        // Update title with data-i18n-title
        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            const key = el.getAttribute('data-i18n-title');
            const translation = this.t(key);
            if (translation && translation !== key) {
                el.title = translation;
            }
        });

        // Update page title
        const titleEl = document.querySelector('title[data-i18n]');
        if (titleEl) {
            const key = titleEl.getAttribute('data-i18n');
            const translation = this.t(key);
            if (translation && translation !== key) {
                document.title = translation;
            }
        }
    }

    /**
     * Setup language toggle buttons
     */
    setupLanguageToggle() {
        document.querySelectorAll('.lang-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const lang = e.target.dataset.lang;
                if (lang && lang !== this.currentLang) {
                    this.switchLanguage(lang);
                }
            });
        });

        this.updateLanguageButtons();
    }

    /**
     * Update active state of language buttons
     */
    updateLanguageButtons() {
        document.querySelectorAll('.lang-btn').forEach(btn => {
            const lang = btn.dataset.lang;
            if (lang === this.currentLang) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });
    }

    /**
     * Switch to a different language
     */
    async switchLanguage(lang) {
        if (!this.supportedLangs.includes(lang)) {
            console.error('Unsupported language:', lang);
            return false;
        }

        if (lang === this.currentLang) {
            return true;
        }

        return await this.loadTranslations(lang);
    }

    /**
     * Get current language
     */
    getLanguage() {
        return this.currentLang;
    }

    /**
     * Check if current language is RTL
     */
    isRTL() {
        return this.rtlLangs.includes(this.currentLang);
    }

    /**
     * Translate state label
     */
    translateState(state) {
        return this.t(`states.${state}`, state);
    }

    /**
     * Translate recommendation label
     */
    translateRecommendation(rec) {
        const key = rec.replace('/', '_').toLowerCase();
        return this.t(`recommendations.${key}`, rec);
    }

    /**
     * Translate direction label
     */
    translateDirection(dirCode) {
        return this.t(`directions.${dirCode}`, dirCode);
    }

    /**
     * Translate BTC risk level
     */
    translateRiskLevel(level) {
        return this.t(`btc_risk.${level}`, level);
    }

    /**
     * Translate impact label
     */
    translateImpact(impact) {
        return this.t(`impacts.${impact.toLowerCase()}`, impact);
    }
}

// Create global instance
window.i18n = new I18n();
