# Professional Notebook Styling Guide

PyTestLab notebooks are designed to provide a professional, consistent, and visually appealing experience that aligns with modern scientific documentation standards. This guide covers the styling system, customization options, and best practices for creating beautiful, functional notebooks.

## 🎨 Design Philosophy

Our notebook styling follows these core principles:

- **Light Theme Optimized**: Clean, professional appearance suitable for scientific documentation
- **Accessibility First**: High contrast ratios and keyboard navigation support
- **Modern Glassmorphism**: Subtle transparency effects with blur backgrounds
- **Responsive Design**: Seamless experience across desktop, tablet, and mobile devices
- **Performance Focused**: Lightweight CSS with efficient animations

## 🌟 Visual Features

### Color Palette

The PyTestLab notebook theme uses a carefully curated color system:

```css
/* Primary Brand Colors */
--lab-violet: #5333ed    /* Primary actions, input prompts */
--lab-aqua: #04e2dc      /* Secondary actions, output prompts */
--photon-white: #f5f7fa  /* Primary text, clean backgrounds */
--photon-black: #0b0e11  /* Text, high contrast elements */

/* Status Colors */
--status-success: #00b27c
--status-warning: #ffb02e
--status-error: #ff5460
```

### Typography

- **Display Font**: Manrope - Used for headings and emphasis
- **UI Font**: Inter - Used for interface elements and body text
- **Code Font**: IBM Plex Mono - Used for all code content with enhanced readability

#### Code Readability Enhancements

- **Font Size**: 1rem (16px) for code blocks, 0.95rem for outputs
- **Font Weight**: 500-600 for better contrast and readability
- **Line Height**: 1.6 for optimal reading experience
- **Background**: Light gray (#f8fafc) with subtle borders for clear separation
- **Syntax Colors**: High-contrast colors optimized for light backgrounds

### Visual Effects

- **Glassmorphism**: Semi-transparent backgrounds with blur effects
- **Smooth Transitions**: 0.3s cubic-bezier animations
- **Subtle Shadows**: Multi-layered shadows for depth
- **Hover States**: Interactive feedback on all actionable elements

## 📱 Cell Structure

### Code Cells

Code cells feature a distinctive two-part layout:

```
┌─────────────────────────────────────────┐
│ [In 1:] │ # Your Python code here       │
│  CODE   │ import pytestlab              │
│         │ ...                           │
│         │                        [Copy] │
└─────────────────────────────────────────┘
```

**Key Features:**
- **Violet Prompt Area**: Left sidebar with execution number
- **Clean Code Area**: High-contrast syntax highlighting with improved readability
- **Enhanced Background**: Light gray (#f8fafc) background for better text contrast
- **Improved Typography**: 1rem font size with 500-600 font weight
- **Copy Button**: Appears on hover, copies code to clipboard
- **Language Badge**: Bottom-right indicator showing "Python"

### Output Cells

Output cells display results with consistent formatting:

```
┌─────────────────────────────────────────┐
│ [Out 1:]│ Measurement result: 3.14159   │
│   OUT   │ Status: Success               │
│         │                        [Copy] │
└─────────────────────────────────────────┘
```

**Key Features:**
- **Aqua Prompt Area**: Left sidebar with output number
- **High-Contrast Text**: Dark text (#1e293b) on light backgrounds for excellent readability
- **Enhanced Formatting**: Improved font weights and spacing for results
- **Professional Tables**: Clean white backgrounds with blue headers
- **Clear Error Display**: Red text on light pink backgrounds for error visibility
- **Data Visualization**: Enhanced styling for plots and tables

### Markdown Cells

Markdown cells provide rich text formatting:

- **Gradient Headers**: H1 titles with violet-to-aqua gradients
- **Clean Typography**: Optimized line height and spacing
- **Code Highlighting**: Inline code with subtle backgrounds
- **Professional Layout**: Consistent margins and padding

## 🎯 Interactive Features

### Copy to Clipboard

Every code cell includes smart copy functionality:

- **Hover Activation**: Copy button appears on cell hover
- **Clean Code Extraction**: Removes prompts and line numbers
- **Visual Feedback**: Button changes to "✓ Copied" on success
- **Keyboard Shortcut**: `Ctrl/Cmd + C` when cell is focused

### Keyboard Navigation

Professional keyboard navigation support:

- **Tab Navigation**: Navigate between cells
- **Arrow Keys**: `Ctrl + ↑/↓` moves between cells
- **Copy Shortcut**: `Ctrl/Cmd + Shift + C` copies all code cells
- **Focus Indicators**: Clear visual focus states

### Responsive Design

Adaptive layout for all screen sizes:

- **Desktop**: Full two-column layout with sidebar prompts
- **Tablet**: Adjusted spacing and button sizes
- **Mobile**: Stacked layout with top prompts

## 🛠 Customization Options

### CSS Variables

Customize the appearance using CSS custom properties:

```css
:root {
  /* Adjust primary colors */
  --lab-violet: #6366f1;
  --lab-aqua: #06b6d4;
  
  /* Modify spacing */
  --spacing-md: 1.25rem;
  --spacing-lg: 2rem;
  
  /* Update border radius */
  --border-radius-md: 12px;
  --border-radius-lg: 20px;
  
  /* Code readability improvements */
  --code-bg: #f8fafc;
  --code-text: #1e293b;
  --code-border: #cbd5e1;
}
```

### High-Contrast Code Styling

Enhanced syntax highlighting with improved readability:

```css
/* High-contrast syntax colors */
.token.keyword { color: #8b5cf6; font-weight: 700; }
.token.string { color: #16a34a; font-weight: 500; }
.token.number { color: #dc2626; font-weight: 600; }
.token.function { color: #1d4ed8; font-weight: 600; }
.token.comment { color: #64748b; font-style: italic; }
.token.operator { color: #1e293b; font-weight: 600; }
```

### Dark Mode Support

While optimized for light themes, dark mode can be enabled:

```css
@media (prefers-color-scheme: dark) {
  :root {
    --photon-white: #1e293b;
    --photon-black: #f1f5f9;
    /* Additional dark mode overrides */
  }
}
```

### Custom Cell Types

Create custom cell styling for specific content:

```css
/* Research note cells */
.cell[data-type="research-note"] {
  border-left: 4px solid var(--status-warning);
  background: linear-gradient(135deg, 
    rgba(255, 176, 46, 0.05) 0%, 
    rgba(255, 176, 46, 0.02) 100%);
}

/* Important code cells */
.cell[data-type="critical"] {
  border: 2px solid var(--status-error);
  box-shadow: 0 0 20px rgba(255, 84, 96, 0.1);
}
```

## 📊 Data Visualization

### Tables

Enhanced table styling for data presentation with improved readability:

- **High-Contrast Headers**: Blue gradient headers with bold white text
- **Clean White Background**: Professional white table background
- **Subtle Row Striping**: Light gray alternating rows (#f8fafc)
- **Improved Typography**: Medium font weight (500) for better readability
- **Clear Borders**: Defined borders (#cbd5e1) for cell separation
- **Hover Effects**: Subtle row highlighting on interaction
- **Responsive Design**: Horizontal scrolling on small screens

### Plots and Images

Optimized display for scientific visualizations:

- **Rounded Corners**: Consistent with overall design
- **Drop Shadows**: Subtle depth effects
- **Zoom Interaction**: Hover effects for better visibility
- **Responsive Sizing**: Automatic scaling for different screens

### Code Output

Special handling for different output types with enhanced readability:

- **Text Output**: High-contrast dark text (#1e293b) on light backgrounds
- **Improved Typography**: 0.95rem font size with 500 font weight
- **Clear Backgrounds**: Light gray (#f8fafc) with defined borders
- **HTML Output**: Preserved formatting with theme integration
- **Error Messages**: Bold red text (#dc2626) on light pink backgrounds (#fef2f2)
- **Enhanced Borders**: Clear visual separation with subtle shadows
- **Rich Display**: Enhanced styling for Jupyter rich output

## 🚀 Performance Optimizations

### Lazy Loading

Styling enhancements are applied progressively:

- **Intersection Observer**: Effects added when cells become visible
- **Debounced Events**: Optimized scroll and resize handlers
- **Minimal DOM Manipulation**: Efficient CSS-only animations

### Resource Efficiency

- **Lightweight CSS**: Optimized selectors and minimal redundancy
- **Hardware Acceleration**: GPU-accelerated transforms and filters
- **Reduced Reflows**: Layout-stable animations and transitions

## 🎨 Best Practices

### Notebook Structure

1. **Start with a Title Cell**: Use the professional header format
2. **Include Setup Cell**: Standard imports and configuration
3. **Section Headers**: Clear navigation with numbered sections
4. **Code Documentation**: Comments explaining each step
5. **Conclusion Cell**: Summary and next steps

### Content Guidelines

1. **Consistent Spacing**: Use standard margins between sections
2. **Clear Code**: Well-commented, readable Python code with high contrast
3. **Professional Tone**: Academic but accessible language
4. **Visual Hierarchy**: Proper heading levels and emphasis
5. **Error Handling**: Include try/catch blocks where appropriate
6. **Readability Focus**: Ensure all text has sufficient contrast ratios
7. **Code Clarity**: Use descriptive variable names and clear comments

### Accessibility

1. **Keyboard Navigation**: Ensure all features work without mouse
2. **Screen Reader Support**: Proper ARIA labels and semantic markup
3. **High Contrast**: WCAG-compliant color ratios (minimum 4.5:1 for normal text)
4. **Reduced Motion**: Respect user motion preferences
5. **Code Readability**: Enhanced font weights and sizes for better visibility
6. **Clear Visual Hierarchy**: Distinct styling for different content types
7. **Error Visibility**: High-contrast error messages with clear backgrounds

## 🔧 Troubleshooting

### Common Issues

**Copy Button Not Appearing**
- Ensure JavaScript is enabled
- Check browser console for errors
- Verify CSS files are loaded correctly

**Styling Not Applied**
- Clear browser cache
- Check CSS file paths in mkdocs.yml
- Verify notebook cell structure

**Mobile Layout Issues**
- Test responsive breakpoints
- Check viewport meta tag
- Verify touch interactions

### Browser Compatibility

- **Chrome**: Full support for all features
- **Firefox**: Full support with minor visual differences
- **Safari**: Full support with backdrop-filter optimizations
- **Edge**: Full support for all features

## 📚 Examples

### Professional Title Cell

```markdown
# PyTestLab Tutorial: Advanced Measurements

<div style="background: linear-gradient(135deg, #5333ed 0%, #04e2dc 100%); padding: 1.5rem; border-radius: 12px; margin: 1rem 0; color: white;">
    <h2 style="margin: 0 0 0.5rem 0; color: white;">✨ PyTestLab Professional Notebook</h2>
    <p style="margin: 0; opacity: 0.9; font-size: 1.1rem;">Learn advanced measurement techniques with real-world examples.</p>
</div>
```

### Section Header

```markdown
## 2. Data Acquisition Setup

Configure instruments for high-precision measurements.

---
```

### Code Cell with Documentation

```python
# Configure oscilloscope for precise timing measurements
# This example shows best practices for instrument setup

osc = AutoInstrument.from_config("keysight/DSOX1204G")

# Set high-resolution mode for better accuracy
osc.set_acquisition_mode("HIRes")
print(f"✅ Oscilloscope configured: {osc.id()}")
```

**Readability Features:**
- High-contrast syntax highlighting with bold keywords
- Clear distinction between comments (italic) and code
- Enhanced font weight (500-600) for better visibility
- Light gray background with defined borders
- Optimal 1rem font size with 1.6 line height

## 🎭 Advanced Styling

### Custom Animations

```css
/* Smooth cell entrance animation */
@keyframes cellFadeIn {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.nb-cell {
  animation: cellFadeIn 0.4s ease-out;
}
```

### Enhanced Interactions

```css
/* Professional hover states */
.nb-cell:hover {
  transform: translateY(-2px);
  box-shadow: 
    0 8px 40px rgba(83, 51, 237, 0.12),
    0 4px 20px rgba(0, 0, 0, 0.03);
}

/* Interactive copy button */
.copy-button:hover {
  background: linear-gradient(135deg, #6d28d9, var(--lab-aqua));
  transform: translateY(-2px) scale(1.05);
}
```

This comprehensive styling system ensures that PyTestLab notebooks maintain a professional, consistent appearance while providing excellent user experience across all devices and use cases.