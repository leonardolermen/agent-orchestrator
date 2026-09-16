/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // As MESMAS cores de classe de custo do canvas de execução. Se REGRA
        // fosse verde numa tela e azul na outra, a pessoa aprenderia duas
        // linguagens para ler a mesma coisa.
        tinta: "#1c1c1c",
        papel: "#faf9f7",
        borda: "#d8d4cd",
        regra: "#2f7a4d",
        agente: "#a86a10",
        crew: "#8a6d1f",
        humano: "#2a5d9c",
        lacuna: "#8a6d1f",
        "lacuna-fundo": "#fdf6e0",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
};
