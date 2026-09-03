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

HOOK_METHOD(CommandGui, OnInit, () -> void)
{
    LOG_HOOK("HOOK_METHOD -> CommandGui::OnInit -> Begin (AgentHook.cpp)\n")
    super();
    AgentSocket_Init();
}
