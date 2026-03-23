package com.analyzer;

import org.json.simple.JSONObject;

public class MethodLineInfo {
    public int startLine;
    public int endLine;
    public String methodName;
    public int parameterCount;

    public MethodLineInfo(int startLine, int endLine, String methodName, int parameterCount) {
        this.startLine = startLine;
        this.endLine = endLine;
        this.methodName = methodName;
        this.parameterCount = parameterCount;
    }

    public JSONObject toJSON() {
        JSONObject jsonObject = new JSONObject();
        jsonObject.put("startLine", startLine);
        jsonObject.put("endLine", endLine);
        jsonObject.put("methodName", methodName);
        jsonObject.put("parameterCount", parameterCount);
        return jsonObject;
    }
}