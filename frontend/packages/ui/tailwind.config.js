/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [],
  theme: {
    extend: {
      colors: {
        admin: {
          bg: 'var(--color-bg)',
          'primary-text': 'var(--color-primary-text)',
          accent: 'var(--color-accent)',
        },
        citizen: {
          bg: 'var(--color-bg)',
          'primary-text': 'var(--color-primary-text)',
          accent: 'var(--color-accent)',
        },
        offline: {
          bg: 'var(--color-bg)',
          'primary-text': 'var(--color-primary-text)',
          accent: 'var(--color-accent)',
        },
      },
    },
  },
  plugins: [],
};
