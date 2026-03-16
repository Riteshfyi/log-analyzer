"use client";

import type React from "react";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Play, Bot, LogIn, CheckCircle2, AlertCircle } from "lucide-react";
import { FileUpload } from "@/components/file-upload";

interface SearchFormProps {
  onSearch: (params: any) => void;
  loading: boolean;
  isAuthenticated: boolean;
  authError?: string;
}

const SEARCH_FIELDS = [
  { value: "fields.WEBEX_TRACKINGID.keyword", label: "Webex Tracking ID" },
  { value: "fields.mobiusCallId.keyword", label: "Mobius Call ID" },
  { value: "fields.USER_ID.keyword", label: "User ID" },
  { value: "fields.DEVICE_ID.keyword", label: "Device ID" },
  { value: "fields.WEBEX_MEETING_ID.keyword", label: "Webex Meeting ID" },
  { value: "fields.LOCUS_ID.keyword", label: "Locus ID" },
  { value: "fields.sipCallId.keyword", label: "SIP Call ID" },
  { value: "callId.keyword", label: "Call ID" },
  { value: "traceId.keyword", label: "Trace ID" },
  { value: "sessionId", label: "Session ID" },
  { value: "message", label: "Global" },
];

const TIME_FILTERS = [
  { value: "none", label: "None" },
  { value: "last-15-minutes", label: "Last 15 minutes" },
  { value: "last-30-minutes", label: "Last 30 minutes" },
  { value: "last-1-hour", label: "Last 1 hour" },
  { value: "last-12-hours", label: "Last 12 hours" },
  { value: "last-24-hours", label: "Last 24 hours" },
  { value: "last-3-days", label: "Last 3 days" },
  { value: "last-7-days", label: "Last 7 days" },
  { value: "last-15-days", label: "Last 15 days" },
];

const SERVICES = [
  { value: "mobius", label: "Mobius" },
  { value: "wdm", label: "WDM" },
  { value: "locus", label: "Locus" },
  { value: "mercury", label: "Mercury" },
  { value: "sse", label: "SSE" },
  { value: "mse", label: "MSE" },
  { value: "kamailio", label: "Kamailio" }
];

const REGIONS = [
  { value: "us", label: "US" },
  { value: "eu", label: "EU" },
];

const ENVIRONMENTS = [
  { value: "prod", label: "Production" },
  { value: "int", label: "Integration" },
];

const LLMS = [
  { value: "gpt-5.2", label: "GPT-4.1" },
  // { value: "gemini", label: "Gemini" },
];

export function SearchForm({ onSearch, loading, isAuthenticated, authError }: SearchFormProps) {
  const [searchValue, setSearchValue] = useState("");
  const [searchField, setSearchField] = useState("");
  const [timeFilter, setTimeFilter] = useState("");
  const [llm, setLlm] = useState("gpt-5.2");
  const [selectedServices, setSelectedServices] = useState<string[]>([]);
  const [selectedRegions, setSelectedRegions] = useState<string[]>([]);
  const [selectedEnvironments, setSelectedEnvironments] = useState<string[]>([]);
  const [detailedAnalysis, setDetailedAnalysis] = useState(false);
  const [uploadedFile, setUploadedFile] = useState<{ name: string; content: string } | null>(null);

  const handleServiceChange = (service: string, checked: boolean) => {
    if (checked) {
      setSelectedServices((prev) => [...prev, service]);
    } else {
      setSelectedServices((prev) => prev.filter((s) => s !== service));
    }
  };

  const handleRegionChange = (region: string, checked: boolean) => {
    if (checked) {
      setSelectedRegions((prev) => [...prev, region]);
    } else {
      setSelectedRegions((prev) => prev.filter((r) => r !== region));
    }
  }

  const handleEnvironmentChange = (environment: string, checked: boolean) => {
    if (checked) {
      setSelectedEnvironments((prev) => [...prev, environment]);
    } else {
      setSelectedEnvironments((prev) => prev.filter((e) => e !== environment));
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    const searchParams: any = {
      llm,
      searchValue: searchValue.trim(),
      searchField,
      services: selectedServices,
      regions: selectedRegions,
      environments: selectedEnvironments,
      timeFilter,
      detailedAnalysis,
    };

    if (uploadedFile) {
      searchParams.uploadedFile = uploadedFile;
    }

    onSearch(searchParams);
  };

  const handleWebexLogin = () => {
    window.location.href = "/api/auth/login";
  };

  return (
    <Card className="border-gray-200 min-h-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-black">
          <Bot className="h-6 w-6" />
          LogAnalyzer
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="flex flex-col gap-4">
            {/* Webex OAuth Login */}
            <div className="space-y-2">
              <Label className="text-black font-medium">Authentication</Label>
              {isAuthenticated ? (
                <div className="flex items-center gap-2 p-2.5 bg-green-50 border border-green-200 rounded-md">
                  <CheckCircle2 className="h-4 w-4 text-green-600 flex-shrink-0" />
                  <span className="text-sm text-green-700 font-medium">Signed in with Webex</span>
                </div>
              ) : (
                <>
                  <Button
                    type="button"
                    onClick={handleWebexLogin}
                    disabled={loading}
                    className="w-full bg-black text-white hover:bg-gray-800 flex items-center justify-center gap-2"
                  >
                    <LogIn className="h-4 w-4" />
                    Sign in with Webex
                  </Button>
                  {authError && (
                    <div className="flex items-center gap-2 p-2 bg-red-50 border border-red-200 rounded-md">
                      <AlertCircle className="h-4 w-4 text-red-500 flex-shrink-0" />
                      <span className="text-xs text-red-600">{authError}</span>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Search Field Selector */}
            <div className="space-y-2">
              <Label htmlFor="searchField" className="text-black font-medium">
                Search Field
              </Label>
              <Select value={searchField} onValueChange={setSearchField}>
                <SelectTrigger className="border-gray-300">
                  <SelectValue placeholder="Select search field" />
                </SelectTrigger>
                <SelectContent>
                  {SEARCH_FIELDS.map((field) => (
                    <SelectItem key={field.value} value={field.value}>
                      {field.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* LLM Selector */}
            <div className="space-y-2">
              <Label htmlFor="llm" className="text-black font-medium">
                LLM
              </Label>
              <Select value={llm} onValueChange={setLlm}>
                <SelectTrigger className="border-gray-300">
                  <SelectValue placeholder="Select LLM" />
                </SelectTrigger>
                <SelectContent>
                  {LLMS.map((llmOption) => (
                    <SelectItem key={llmOption.value} value={llmOption.value}>
                      {llmOption.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Time Filter Selector */}
            <div className="space-y-2">
              <Label htmlFor="timeFilter" className="text-black font-medium">
                Time Filter
              </Label>
              <Select value={timeFilter} onValueChange={setTimeFilter}>
                <SelectTrigger className="border-gray-300">
                  <SelectValue placeholder="Select time filter" />
                </SelectTrigger>
                <SelectContent>
                  {TIME_FILTERS.map((filter) => (
                    <SelectItem key={filter.value} value={filter.value}>
                      {filter.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Services Selector */}
            <div className="space-y-2">
              <Label className="text-black font-medium">Services</Label>
              <div className="grid grid-cols-2 gap-3 p-2 border border-gray-300 rounded-md">
                {SERVICES.map((service) => (
                  <div
                    key={service.value}
                    className="flex items-center space-x-2"
                  >
                    <Checkbox
                      id={service.value}
                      checked={selectedServices.includes(service.value)}
                      onCheckedChange={(checked: boolean) =>
                        handleServiceChange(service.value, checked as boolean)
                      }
                    />
                    <Label
                      htmlFor={service.value}
                      className="text-sm text-black cursor-pointer"
                    >
                      {service.label}
                    </Label>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Environment Selector */}
          <div className="space-y-2">
            <Label className="text-black font-medium">Environments</Label>
            <div className="grid grid-cols-2 gap-3 p-2 border border-gray-300 rounded-md">
              {ENVIRONMENTS.map((environment) => (
                <div
                  key={environment.value}
                  className="flex items-center space-x-2"
                >
                  <Checkbox
                    id={environment.value}
                    checked={selectedEnvironments.includes(environment.value)}
                    onCheckedChange={(checked: boolean) =>
                      handleEnvironmentChange(environment.value, checked as boolean)
                    }
                  />
                  <Label
                    htmlFor={environment.value}
                    className="text-sm text-black cursor-pointer"
                  >
                    {environment.label}
                  </Label>
                </div>
              ))}
            </div>
          </div>

          {/* Region Selector */}
          <div className="space-y-2">
            <Label className="text-black font-medium">Regions</Label>
            <div className="grid grid-cols-2 gap-3 p-2 border border-gray-300 rounded-md">
              {REGIONS.map((region) => (
                <div
                  key={region.value}
                  className="flex items-center space-x-2"
                >
                  <Checkbox
                    id={region.value}
                    checked={selectedRegions.includes(region.value)}
                    onCheckedChange={(checked: boolean) =>
                      handleRegionChange(region.value, checked as boolean)
                    }
                  />
                  <Label
                    htmlFor={region.value}
                    className="text-sm text-black cursor-pointer"
                  >
                    {region.label}
                  </Label>
                </div>
              ))}
            </div>
          </div>

          {/* Detailed Analysis */}
          <div className="flex items-center space-x-3 p-2 border border-gray-300 rounded-md">
            <Checkbox
              id="detailedAnalysis"
              checked={detailedAnalysis}
              onCheckedChange={(checked: boolean) =>
                setDetailedAnalysis(checked as boolean)
              }
            />
            <div className="grid gap-1.5 leading-none">
              <Label
                htmlFor="detailedAnalysis"
                className="text-sm text-black font-medium cursor-pointer"
              >
                Detailed Analysis
              </Label>
              <p className="text-xs text-gray-500">
                Include raw logs in analysis output
              </p>
            </div>
          </div>

          {/* SDK Log File Upload */}
          <FileUpload onFileSelect={setUploadedFile} disabled={loading} />

          {/* Search Input */}
          <div className="space-y-2">
            <Label htmlFor="searchValue" className="text-black font-medium">
              Search Value
            </Label>
            <Input
              id="searchValue"
              value={searchValue}
              onChange={(e) => setSearchValue(e.target.value)}
              placeholder="Enter tracking ID or search value..."
              className="border-gray-300"
            />
            <Button
              type="submit"
              disabled={loading || !isAuthenticated || (!uploadedFile && (!searchField || !searchValue))}
              className="bg-[#00BCEBFF] text-white hover:bg-[#00BCEB99] px-6 w-full"
            >
              {loading ? (
                <div className="flex items-center gap-2">
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Analyzing...
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <Play className="h-4 w-4" />
                  Start Analysis
                </div>
              )}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
