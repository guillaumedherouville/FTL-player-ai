#pragma once
#include <string>

void AgentSocket_Init();
bool AgentSocket_Send(const std::string &json);
std::string AgentSocket_Recv();
