import { alpha, createTheme } from "@mui/material/styles";

const theme = createTheme({
  palette: {
    mode: "dark",
    primary: {
      main: "#7dd3fc",
      light: "#bae6fd",
      dark: "#38bdf8",
    },
    secondary: {
      main: "#a7f3d0",
    },
    background: {
      default: "#0d0f12",
      paper: "#15191f",
    },
    text: {
      primary: "#f3f7fb",
      secondary: "#9aa8b7",
    },
    divider: "rgba(154, 168, 183, 0.16)",
  },
  shape: {
    borderRadius: 6,
  },
  typography: {
    fontFamily: [
      "Inter",
      "-apple-system",
      "BlinkMacSystemFont",
      '"Segoe UI"',
      "Roboto",
      "sans-serif",
    ].join(","),
    button: {
      textTransform: "none",
      letterSpacing: 0,
      fontWeight: 700,
    },
    h4: {
      letterSpacing: 0,
    },
    overline: {
      letterSpacing: "0.08em",
      fontWeight: 800,
    },
  },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
          border: "1px solid rgba(154, 168, 183, 0.14)",
          boxShadow: "0 18px 40px rgba(0,0,0,0.18)",
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 6,
        },
        contained: {
          color: "#071017",
          boxShadow: "none",
        },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          borderRadius: 6,
          backgroundColor: alpha("#ffffff", 0.025),
          "& fieldset": {
            borderColor: "rgba(154, 168, 183, 0.18)",
          },
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: "#11151a",
          borderRight: "1px solid rgba(154, 168, 183, 0.14)",
        },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          color: "#dce6ee",
          "&.Mui-selected": {
            backgroundColor: "rgba(125, 211, 252, 0.12)",
          },
          "&.Mui-selected:hover": {
            backgroundColor: "rgba(125, 211, 252, 0.17)",
          },
        },
      },
    },
  },
});

export default theme;
