import { AgentHoverCard } from "@/panels/chat/AgentHoverCard";
import type { ChatAgent, ChatTab } from "@/panels/chat/constants";
import { statusColor } from "@/panels/chat/formatting";
import { Icon } from "@/panels/chat/icons";

type Setter<T> = React.Dispatch<React.SetStateAction<T>>;

interface ChatHeaderProps {
  selectedAgent: ChatAgent;
  chatTab: ChatTab;
  setChatTab: Setter<ChatTab>;
  chatSidebarOpen: boolean;
  setChatSidebarOpen: Setter<boolean>;
  newConversation: () => void;
  rightPanel: "files" | null;
  setRightPanel: (panel: "files" | null) => void;
  setInCall: (inCall: boolean) => void;
  setCallSeconds: Setter<number>;
  chatSearchOpen: boolean;
  setChatSearchOpen: Setter<boolean>;
  setChatSearchTerm: Setter<string>;
  theme: string;
  toggleTheme: () => void;
}

interface ChatHeaderTabsProps {
  chatTab: ChatTab;
  setChatTab: Setter<ChatTab>;
  newConversation: () => void;
}

function ChatHeaderTabs({ chatTab, setChatTab, newConversation }: ChatHeaderTabsProps): JSX.Element {
  return (
    <nav className="chat-tabs" aria-label="Chat tabs">
      <button
        type="button"
        className={chatTab === "chat" ? "chat-tabs__tab chat-tabs__tab--active" : "chat-tabs__tab"}
        onClick={() => setChatTab("chat")}
      >
        Chat
      </button>
      <button
        type="button"
        className={chatTab === "activity" ? "chat-tabs__tab chat-tabs__tab--active" : "chat-tabs__tab"}
        onClick={() => setChatTab("activity")}
      >
        Activity
      </button>
      <button
        className="chat-tabs__new"
        type="button"
        title="New chat"
        onClick={newConversation}
        style={{ width: 24, height: 24, marginLeft: 4 }}
      >
        <Icon name="plus" size={14} />
      </button>
    </nav>
  );
}

interface ChatHeaderActionsProps {
  rightPanel: "files" | null;
  setRightPanel: (panel: "files" | null) => void;
  setInCall: (inCall: boolean) => void;
  setCallSeconds: Setter<number>;
  chatSearchOpen: boolean;
  setChatSearchOpen: Setter<boolean>;
  setChatSearchTerm: Setter<string>;
  theme: string;
  toggleTheme: () => void;
}

function ChatHeaderActions({
  rightPanel,
  setRightPanel,
  setInCall,
  setCallSeconds,
  chatSearchOpen,
  setChatSearchOpen,
  setChatSearchTerm,
  theme,
  toggleTheme,
}: ChatHeaderActionsProps): JSX.Element {
  const startCall = () => {
    setCallSeconds(() => 0);
    setInCall(true);
  };

  return (
    <>
      <div className="chat-header__spacer" />
      <button
        className="icon-btn chat-header__action"
        type="button"
        title="Files"
        aria-pressed={rightPanel === "files"}
        onClick={() => setRightPanel(rightPanel === "files" ? null : "files")}
      >
        <Icon name="file" size={16} />
      </button>
      <button
        className="icon-btn chat-header__action"
        type="button"
        title="Voice call"
        onClick={startCall}
      >
        <Icon name="phone" size={16} />
      </button>
      <button
        className="icon-btn chat-header__action"
        type="button"
        title="Search"
        aria-pressed={chatSearchOpen}
        onClick={() => {
          setChatSearchOpen((open) => {
            if (open) setChatSearchTerm("");
            return !open;
          });
        }}
      >
        <Icon name="search" size={16} />
      </button>
      <button
        className="icon-btn chat-header__action"
        type="button"
        title="Theme"
        onClick={toggleTheme}
      >
        <Icon name={theme === "light" ? "sun" : "moon"} size={16} />
      </button>
    </>
  );
}

export function ChatHeader(props: ChatHeaderProps): JSX.Element {
  const {
    selectedAgent,
    chatTab,
    setChatTab,
    chatSidebarOpen,
    setChatSidebarOpen,
    newConversation,
    rightPanel,
    setRightPanel,
    setInCall,
    setCallSeconds,
    chatSearchOpen,
    setChatSearchOpen,
    setChatSearchTerm,
    theme,
    toggleTheme,
  } = props;

  return (
    <header className="chat-header">
      <button
        className="icon-btn chat-header__rail-toggle"
        type="button"
        aria-label="Toggle chat sidebar"
        aria-pressed={chatSidebarOpen}
        onClick={() => setChatSidebarOpen((open) => !open)}
      >
        <Icon name="panel" size={16} />
      </button>
      <div className="chat-header__agent">
        <div>
          <strong>
            {selectedAgent.name}
            <span
              className="chat-header__status-dot"
              style={{ background: statusColor(selectedAgent.status) }}
              aria-label={`Status: ${selectedAgent.status}`}
            />
          </strong>
          <span>{selectedAgent.role}</span>
        </div>
        <AgentHoverCard agent={selectedAgent} />
      </div>
      <ChatHeaderTabs chatTab={chatTab} setChatTab={setChatTab} newConversation={newConversation} />
      <ChatHeaderActions
        rightPanel={rightPanel}
        setRightPanel={setRightPanel}
        setInCall={setInCall}
        setCallSeconds={setCallSeconds}
        chatSearchOpen={chatSearchOpen}
        setChatSearchOpen={setChatSearchOpen}
        setChatSearchTerm={setChatSearchTerm}
        theme={theme}
        toggleTheme={toggleTheme}
      />
    </header>
  );
}

export { type ChatHeaderProps };
