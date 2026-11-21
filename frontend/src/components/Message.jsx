import PropTypes from "prop-types";
import "../styles/components/Message.css";
import ReactMarkdown from "react-markdown";

export default function Message({ text, sender }) {
  return (
    <div className={`message-wrapper ${sender}`}>
      <div className="message-content">
        <div className="message-avatar">{sender === "user" ? "👤" : "🤖"}</div>
        <div className="message-bubble">
          <div className="message-text">
            <ReactMarkdown>{text}</ReactMarkdown>
          </div>
        </div>
      </div>
    </div>
  );
}

Message.propTypes = {
  text: PropTypes.string.isRequired,
  sender: PropTypes.string.isRequired,
};
