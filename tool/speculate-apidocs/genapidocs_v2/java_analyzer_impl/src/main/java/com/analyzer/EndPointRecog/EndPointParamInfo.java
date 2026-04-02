package com.analyzer.EndPointRecog;

import com.analyzer.EndPointRecog.ParameterAnnotation.paramLoction;

import org.json.simple.JSONObject;

import soot.Type;

public class EndPointParamInfo {
  public String name;
  public int index;
  public Boolean required;
  public paramLoction in;
  public String defaultValue;
  public Type type;

  public EndPointParamInfo(String name, int index, Boolean required, paramLoction in, String defaultValue, Type type) {
    this.name = name;
    this.index = index;
    this.required = required;
    this.in = in;
    this.defaultValue = defaultValue;
    this.type=type;
  }

  public JSONObject toJSON() {
    JSONObject paramObject = new JSONObject();
    paramObject.put("name", this.name);
    paramObject.put("index", this.index);

    if (this.required != null) {
      paramObject.put("required", this.required);
    }

    if (this.in != null) {
      paramObject.put("in", this.in.toString());
    }

    if (this.defaultValue != null) {
      paramObject.put("defaultValue", this.defaultValue);
    }

    if (this.type != null) {
      paramObject.put("type", this.type.toString());
    }

    return paramObject;
  }


}
