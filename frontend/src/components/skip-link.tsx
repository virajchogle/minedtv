/**
 * "Skip to main content": invisible until it receives keyboard focus (the
 * first Tab stop on every page), then docks visibly in the top-left corner
 * so a keyboard/screen-reader user can jump past the nav straight to
 * `#main-content` instead of tabbing through it on every single page.
 */
export function SkipLink() {
  return (
    <a href="#main-content" className="mtv-skip-link">
      Skip to main content
    </a>
  );
}
