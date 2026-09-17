/** @type {import('tailwindcss').Config} */
export default {
  // `class` e não `media`: o modo é do PRODUTO, não do sistema operacional. O
  // default é escuro (ver `main.tsx`), e o botão alterna — se fosse `media`, a
  // escolha da pessoa perderia para a preferência do SO a cada visita.
  darkMode: "class",
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
        // O escuro. As cores de CLASSE DE CUSTO mudam de tom mas não de
        // matiz: verde continua REGRA nos dois temas, senão a pessoa
        // aprenderia duas linguagens para ler a mesma coisa.
        noite: {
          fundo: "#16161a",
          painel: "#1c1c21",
          cartao: "#22222a",
          borda: "#32323c",
          tinta: "#e8e6e3",
          fraca: "#9a968f",
          regra: "#5cc48a",
          agente: "#e0a447",
          crew: "#d4b256",
          humano: "#6ba4e8",
          "lacuna-fundo": "#2b2718",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
};
