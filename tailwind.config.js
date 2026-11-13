export default {
  content: ['./frontend/index.html', './frontend/*.js'],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'sans-serif'] },
      colors: { accent: '#6ee7b7' }
    }
  },
  plugins: []
};
