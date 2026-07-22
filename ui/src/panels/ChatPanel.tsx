// US-CONV-01..04, US-CONV-07: the conversational chat surface. The public entry
// point is a thin orchestrator; the rendering, state and data hooks live in the
// chat/ sub-module so every file stays under the structural floor.

import { useChatPanel } from "@/panels/chat/useChatPanel";
import { ChatAgentSidebar } from "@/panels/chat/ChatAgentSidebar";
import { ChatHeader } from "@/panels/chat/ChatHeader";
import { ChatMessages } from "@/panels/chat/ChatMessages";
import { ChatComposer } from "@/panels/chat/ChatComposer";
import { FilesPanel } from "@/panels/chat/FilesPanel";
import { SubRunPanel } from "@/panels/chat/SubRunPanel";
import { CHAT_AGENTS } from "@/panels/chat/constants";
import { MAX_ATTACHMENTS, MAX_ATTACHMENT_BYTES } from "@/panels/chat/constants";
import { formatBytes } from "@/panels/chat/attachmentUtils";
import { Icon } from "@/panels/chat/icons";

export function ChatPanel(): JSX.Element {
  const chat = useChatPanel();

  return (
    <section
      className={`panel chat chat-v3 ${chat.chatSidebarOpen ? "chat-v3--rail-open" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        chat.setDragOver(true);
      }}
      onDragLeave={(e) => {
        if (e.currentTarget === e.target) chat.setDragOver(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        chat.setDragOver(false);
        void chat.addFiles(e.dataTransfer.files);
      }}
    >
      <ChatAgentSidebar
        open={chat.chatSidebarOpen}
        agents={CHAT_AGENTS}
        activeAgent={chat.selectedAgent}
        railItems={chat.railItems}
        railTerm={chat.railTerm}
        railState={chat.rail.state}
        onRailTerm={chat.setRailTerm}
        onNew={chat.newConversation}
        onSelectAgent={(agent) => {
          chat.setSelectedAgentId(agent.id);
          chat.setChatTab("chat");
        }}
        onSelectConversation={chat.selectConversation}
        onDeleted={(id) => {
          if (id === chat.activeId) chat.newConversation();
          chat.rail.reload();
        }}
        onRenamed={() => chat.rail.reload()}
        loadMore={() => void chat.rail.loadMore()}
      />

      <main className="chat-stage">
        <ChatHeader
          selectedAgent={chat.selectedAgent}
          chatTab={chat.chatTab}
          setChatTab={chat.setChatTab}
          chatSidebarOpen={chat.chatSidebarOpen}
          setChatSidebarOpen={chat.setChatSidebarOpen}
          newConversation={chat.newConversation}
          rightPanel={chat.rightPanel}
          setRightPanel={chat.setRightPanel}
          chatSearchOpen={chat.chatSearchOpen}
          setChatSearchOpen={chat.setChatSearchOpen}
          setChatSearchTerm={chat.setChatSearchTerm}
          theme={chat.theme}
          toggleTheme={chat.toggleTheme}
        />

        {chat.chatSearchOpen && (
          <div className="chat-header-search">
            <input
              className="chat-header-search__input"
              type="search"
              placeholder="Search this conversation..."
              aria-label="Search this conversation"
              value={chat.chatSearchTerm}
              onChange={(e) => chat.setChatSearchTerm(e.target.value)}
            />
          </div>
        )}

        {chat.rightPanel === "files" && (
          <FilesPanel attachments={chat.attachments} messages={chat.messages} onClose={() => chat.setRightPanel(null)} />
        )}
        <SubRunPanel
          runId={chat.subRunId}
          full={chat.subRunFull}
          agent={chat.selectedAgent}
          onClose={() => {
            chat.setSubRunId(null);
            chat.setSubRunFull(false);
          }}
          onFull={() => chat.setSubRunFull(true)}
          onCollapse={() => chat.setSubRunFull(false)}
        />
        {chat.dragOver && (
          <div className="chat-drop" role="status">
            <Icon name="paperclip" size={40} />
            <strong>Drop files to attach</strong>
            <span>Up to {MAX_ATTACHMENTS} files, {formatBytes(MAX_ATTACHMENT_BYTES)} each</span>
          </div>
        )}

        <ChatMessages
          chatTab={chat.chatTab}
          slideActive={chat.slideActive}
          streaming={chat.streaming}
          messages={chat.messages}
          visibleMessages={chat.visibleMessages}
          firstVisibleIndex={chat.firstVisibleIndex}
          msgsLoading={chat.msgsLoading}
          msgsError={chat.msgsError}
          isEmpty={chat.isEmpty}
          activeAgent={chat.selectedAgent}
          userName={chat.userName}
          compactedCount={chat.compactedCount}
          compacted={chat.compacted}
          setCompacted={chat.setCompacted}
          clearIndex={chat.clearIndex}
          chatSearchTerm={chat.chatSearchTerm}
          pendingUser={chat.pendingUser}
          pendingAttachments={chat.pendingAttachments}
          showLive={chat.showLive}
          live={chat.live}
          selectedAgent={chat.selectedAgent}
          resolvedHitls={chat.resolvedHitls}
          onResolve={chat.resolveHitl}
          lastAssistantId={chat.lastAssistantId}
          regenerating={chat.regenerating}
          onRegenerate={chat.regenerate}
          onOpenRun={(runId) => chat.setSubRunId(runId)}
          speech={chat.speech}
          stopped={chat.stopped}
          streamError={chat.streamError}
          onWatchAgain={chat.watchAgain}
          onReconnect={chat.reconnect}
          showJump={chat.showJump}
          onJumpToLatest={chat.jumpToLatest}
          onMessagesScroll={chat.onMessagesScroll}
          messagesRef={chat.messagesRef}
        />

        <ChatComposer
          input={chat.input}
          setInput={chat.setInput}
          inputRef={chat.inputRef}
          attachments={chat.attachments}
          removeAttachment={chat.removeAttachment}
          onComposerKey={chat.onComposerKey}
          fileInputRef={chat.fileInputRef}
          addFiles={chat.addFiles}
          streaming={chat.streaming}
          activeId={chat.activeId}
          send={chat.send}
          stopTurn={chat.stopTurn}
          plusOpen={chat.plusOpen}
          setPlusOpen={chat.setPlusOpen}
          slashOpen={chat.slashOpen}
          slashIdx={chat.slashIdx}
          setSlashIdx={(setter) => chat.setSlashIdx(setter)}
          executeSlash={chat.executeSlash}
          readAloud={chat.readAloud}
          setReadAloud={chat.setReadAloudPref}
          dictation={chat.dictation}
          dictationBaseRef={chat.dictationBaseRef}
          attachError={chat.attachError}
          contextRemaining={chat.contextRemaining}
          live={chat.live}
          selectedAgent={chat.selectedAgent}
          onOpenRun={(runId) => chat.setSubRunId(runId)}
        />
      </main>
    </section>
  );
}

export default ChatPanel;
