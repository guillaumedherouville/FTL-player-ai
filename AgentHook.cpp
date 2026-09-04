#include "AgentHook.h"
#include "Global.h"

#include <sys/socket.h>
#include <sys/un.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>

static const char *SOCKET_PATH = "/tmp/ftl_agent.sock";
static int g_sockfd = -1;
static std::string g_recvBuf;

void AgentSocket_Init()
{
    g_sockfd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (g_sockfd < 0) return;

    fcntl(g_sockfd, F_SETFL, O_NONBLOCK);

    struct sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, SOCKET_PATH, sizeof(addr.sun_path) - 1);

    if (connect(g_sockfd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        close(g_sockfd);
        g_sockfd = -1;
    }
}

bool AgentSocket_Send(const std::string &json)
{
    if (g_sockfd < 0) return false;
    std::string msg = json + "\n";
    ssize_t sent = send(g_sockfd, msg.c_str(), msg.size(), MSG_DONTWAIT);
    return sent == (ssize_t)msg.size();
}

std::string AgentSocket_Recv()
{
    if (g_sockfd < 0) return "";

    char buf[4096];
    ssize_t n = recv(g_sockfd, buf, sizeof(buf) - 1, MSG_DONTWAIT);
    if (n > 0) {
        buf[n] = '\0';
        g_recvBuf += buf;
    }

    auto pos = g_recvBuf.find('\n');
    if (pos == std::string::npos) return "";

    std::string line = g_recvBuf.substr(0, pos);
    g_recvBuf.erase(0, pos + 1);
    return line;
}

static std::string QuoteJson(const std::string &s)
{
    std::string out = "\"";
    for (unsigned char c : s) {
        if (c == '"')       out += "\\\"";
        else if (c == '\\') out += "\\\\";
        else if (c == '\n') out += "\\n";
        else if (c == '\r') out += "\\r";
        else if (c < 0x20)  out += ' '; // drop other control chars
        else                out += c;
    }
    out += "\"";
    return out;
}

static std::string SerializeEvent(const ChoiceBox &box)
{
    std::string json = "{\"event\":{\"text\":";
    json += QuoteJson(box.mainText);
    json += ",\"choices\":[";
    for (int i = 0; i < (int)box.choices.size(); i++) {
        if (i > 0) json += ",";
        json += "{\"index\":" + std::to_string(i) + ",\"text\":";
        json += QuoteJson(box.choices[i].text);
        json += "}";
    }
    json += "]}}";
    return json;
}

// Returns -1 on parse failure.
static int ParseChoiceIndex(const std::string &json)
{
    auto pos = json.find("\"index\"");
    if (pos == std::string::npos) return -1;
    pos = json.find(':', pos);
    if (pos == std::string::npos) return -1;
    try {
        return std::stoi(json.substr(pos + 1));
    } catch (...) {
        return -1;
    }
}

HOOK_METHOD(CommandGui, OnInit, () -> void)
{
    LOG_HOOK("HOOK_METHOD -> CommandGui::OnInit -> Begin (AgentHook.cpp)\n")
    super();
    AgentSocket_Init();
}

static std::string lastEventText;
static bool waitingForAction = false;

HOOK_METHOD(CommandGui, OnLoop, () -> void)
{
    LOG_HOOK("HOOK_METHOD -> CommandGui::OnLoop -> Begin (AgentHook.cpp)\n")

    // Enable auto-fire whenever combat is active
    if (this->combatControl.open && !this->combatControl.weapControl.autoFiring) {
        this->combatControl.weapControl.SetAutofiring(true, false);
    }

    // Send event to agent when a new choice box appears
    if (this->choiceBox.bOpen && !this->choiceBox.choices.empty()) {
        if (!waitingForAction && this->choiceBox.mainText != lastEventText) {
            std::string json = SerializeEvent(this->choiceBox);
            if (AgentSocket_Send(json)) {
                lastEventText = this->choiceBox.mainText;
                waitingForAction = true;
            }
        }

        // Poll for a response and dispatch a click
        if (waitingForAction) {
            std::string action = AgentSocket_Recv();
            if (!action.empty()) {
                int idx = ParseChoiceIndex(action);
                if (idx >= 0 && idx < (int)this->choiceBox.choices.size()) {
                    // SDLK_1 = 0x31, SDLK_2 = 0x32, etc.
                    this->choiceBox.KeyDown((SDLKey)(0x31 + idx));
                }
                waitingForAction = false;
            }
        }
    } else {
        // Choice box closed — reset state
        lastEventText.clear();
        waitingForAction = false;
    }

    super();
}
