// tailwind.config.js
module.exports = {
    content: ["./templates/**/*.html", "./static/**/*.js"], // (Make sure your paths match your flask setup)
    theme: {
      extend: {
        // --- PASTE THIS PART START ---
        keyframes: {
          'slide-down': {
            '0%': { transform: 'translateY(-100%)', opacity: '0' },
            '100%': { transform: 'translateY(0)', opacity: '1' },
          }
        },
        animation: {
          'slide-down': 'slide-down 0.8s cubic-bezier(0.16, 1, 0.3, 1)',
        }
        // --- PASTE THIS PART END ---
      }
    },
    plugins: [],
  }