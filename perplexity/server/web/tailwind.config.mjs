/** @type {import('tailwindcss').Config} */

export default {
  content: ['./index.html', './src/**/*.{mjs,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        mono: ['"Space Mono"', 'monospace'],
        sans: ['"Work Sans"', 'sans-serif'],
      },
      colors: {
        void: '#050505',
        concrete: '#1a1a1a',
        acid: '#ccff00',
        'neon-pink': '#ff00ff',
        'neon-blue': '#00ffff',
        danger: '#ff3333',
      },
      boxShadow: {
        hard: '4px 4px 0px 0px #333333',
        'hard-hover': '2px 2px 0px 0px #555555',
        'hard-acid': '4px 4px 0px 0px #ccff00',
        'hard-pink': '4px 4px 0px 0px #990099',
      },
    },
  },
  plugins: [],
}
