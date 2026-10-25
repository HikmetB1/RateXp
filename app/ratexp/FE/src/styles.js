// Inline style objects shared by App.jsx and Dashboard.jsx, so both views draw the same
// boxes. Colours come from the CSS variables in index.css, so they follow the theme.

// Outer frame bundling the inner cards into one section (the chunky "big box").
export const groupBox = {
  display: 'flex',
  flexDirection: 'column',
  gap: 14,
  border: '4px solid var(--ink)',
  padding: 14,
  marginBottom: 24,
  background: 'var(--box)',
  boxShadow: '5px 5px 0 var(--ink)',
}

// The inner card each section sits in. Shared so the cards stay identical.
export const glassCard = {
  margin: 0,
  border: '4px solid var(--ink)',
  padding: '18px 20px',
  background: 'var(--panel)',
  boxShadow: '5px 5px 0 var(--ink)',
}

// Heading shared by every card: a pixel-font block in the button colour.
export const cardHeading = {
  margin: 0,
  display: 'inline-block',
  fontFamily: "'Press Start 2P', monospace",
  fontSize: 13,
  color: 'var(--btnfg)',
  background: 'var(--btn)',
  padding: '7px 11px',
  border: '3px solid var(--ink)',
  boxShadow: '3px 3px 0 var(--box)',
}
