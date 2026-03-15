MapleMCP := module()
    export Start, Stop, UpdatePath;
    local _running, _dir, _ws_path, PollLoop, ProcessRequest, JsonEscape, JsonResponse;

    _running := false;
    _ws_path := "";
    _dir := "C:/Users/willi/mcp-servers/maple-mcp/.bridge";

    JsonEscape := proc(s)
        local r;
        r := convert(s, string);
        r := StringTools:-SubstituteAll(r, "\\", "\\\\");
        r := StringTools:-SubstituteAll(r, "\"", "\\\"");
        r := StringTools:-SubstituteAll(r, "\n", "\\n");
        r := StringTools:-SubstituteAll(r, "\r", "\\r");
        r := StringTools:-SubstituteAll(r, "\t", "\\t");
        r;
    end proc;

    JsonResponse := proc(id, status, resultKey, resultVal)
        cat("{\"id\":\"", JsonEscape(id), "\",\"status\":\"", status,
            "\",\"", resultKey, "\":\"", JsonEscape(resultVal), "\"}");
    end proc;

    UpdatePath := proc(manual_path::string)
        _ws_path := manual_path;
        printf("Path set to: %s\n", _ws_path);
    end proc;

    Start := proc()
        if _running then
            printf("MapleMCP bridge is already running.\n");
            return;
        end if;
        if not FileTools:-Exists(_dir) then
            FileTools:-MakeDirectory(_dir);
        end if;
        try FileTools:-Remove(cat(_dir, "/request")); catch: end try;
        try FileTools:-Remove(cat(_dir, "/response")); catch: end try;
        FileTools:-Text:-WriteFile(cat(_dir, "/ready"), "1");
        _running := true;
        Threads:-Create(PollLoop());
        printf("MapleMCP bridge running.\n");
    end proc;

    Stop := proc()
        _running := false;
        try FileTools:-Remove(cat(_dir, "/ready")); catch: end try;
        try FileTools:-Remove(cat(_dir, "/request")); catch: end try;
        try FileTools:-Remove(cat(_dir, "/response")); catch: end try;
        printf("MapleMCP bridge stopped.\n");
    end proc;

    PollLoop := proc()
        local req_file, resp_file, content, response;
        req_file := cat(_dir, "/request");
        resp_file := cat(_dir, "/response");
        while _running do
            try
                if FileTools:-Exists(req_file) then
                    try
                        content := FileTools:-Text:-ReadFile(req_file);
                    catch:
                        content := "";
                    end try;
                    try FileTools:-Remove(req_file); catch: end try;
                    if content <> "" then
                        try
                            response := ProcessRequest(content);
                        catch:
                            response := JsonResponse("", "error", "error", sprintf("%q", lastexception));
                        end try;
                        try
                            FileTools:-Text:-WriteFile(resp_file, response);
                        catch:
                        end try;
                    end if;
                end if;
            catch:
            end try;
            try Threads:-Sleep(0.05); catch: end try;
        end do;
    end proc;

    ProcessRequest := proc(content)
        local cmd, id, command, params, result;

        id := "";
        command := "";

        try
            cmd := JSON:-Parse(content);
            id := cmd["id"];
            command := cmd["command"];
            params := cmd["params"];
        catch:
            try
                cmd := JSON:-ParseString(content);
                id := cmd["id"];
                command := cmd["command"];
                params := cmd["params"];
            catch:
                return JsonResponse("", "error", "error",
                    cat("Parse failed: ", content[1..min(100, length(content))]));
            end try;
        end try;

        result := "";
        try
            if command = "ping" then
                result := "pong";

            elif command = "execute" then
                result := sprintf("%a", eval(parse(params["statement"], 'statement')));

            elif command = "get_variables" then
                result := sprintf("%a", [anames('user')]);

            elif command = "get_worksheet_path" then
                if _ws_path <> "" then
                    result := _ws_path;
                else
                    result := "NO_FILE";
                end if;

            elif command = "shutdown" then
                _running := false;
                result := "Shutting down";

            else
                result := cat("Unknown command: ", command);
            end if;

            return JsonResponse(id, "ok", "result", result);
        catch:
            return JsonResponse(id, "error", "error", sprintf("%q", lastexception));
        end try;
    end proc;
end module;
