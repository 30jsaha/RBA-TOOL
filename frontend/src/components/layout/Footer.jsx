import "./css/Footer.css";
export default function Footer() {
  return (
    <footer className="text-light text-center py-3 mt-auto">
      <small className="footer-text">© {new Date().getFullYear()} RBA Tool. All rights reserved.</small>
    </footer>
  );
}