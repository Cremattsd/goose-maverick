/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",     // If using Flask templates
    "./static/**/*.html",        // Static HTML files
    "./static/**/*.js",          // JS that may use Tailwind classes
    "./app.py",                  // Tailwind in Flask responses
    "./static/css/input.css"     // Include the CSS file explicitly
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
