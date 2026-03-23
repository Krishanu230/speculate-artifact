package com.analyzer;

import org.json.simple.JSONArray;
import org.json.simple.JSONObject;
import java.util.ArrayList;

public class ClassLineNumbers {
    public ArrayList<MethodLineInfo> methods;
    public String className;
    public int startLine;
    public int endLine;
    public String classFileName;
    public String sootCompatibleFqn;

    public ClassLineNumbers(ArrayList<MethodLineInfo> methods, String className, int startLine, int endLine, String classFileName, String sootCompatibleFqn) {
        this.methods = methods;
        this.className = className;
        this.startLine = startLine;
        this.endLine = endLine;
        this.classFileName = classFileName;
        this.sootCompatibleFqn = sootCompatibleFqn;
    }

    public JSONObject toJSON() {
        JSONObject jsonObject = new JSONObject();
        jsonObject.put("className", className);
        jsonObject.put("startLine", startLine);
        jsonObject.put("endLine", endLine);
        jsonObject.put("classFileName", classFileName);
        jsonObject.put("sootCompatibleFqn", sootCompatibleFqn);
        JSONArray methodsJson = new JSONArray();
        for (MethodLineInfo method : this.methods) {
            methodsJson.add(method.toJSON());
        }
        jsonObject.put("methods", methodsJson);
        return jsonObject;
    }
}