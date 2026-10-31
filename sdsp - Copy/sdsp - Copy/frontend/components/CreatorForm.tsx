"use client";
import { useState, type FormEvent } from "react";
import { post, type Creator, type InstagramCreatorResponse, type Platform } from "@/lib/api";

interface Props {
  onCreated: (creator: Creator) => void;
}

export function CreatorForm({ onCreated }: Props) {
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState<Platform>("youtube");
  const [externalId, setExternalId] = useState("");
  const [handle, setHandle] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [resolvedInstagram, setResolvedInstagram] = useState<InstagramCreatorResponse["instagram_account"] | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      let creator: Creator;
      if (platform === "instagram") {
        const result = await post<InstagramCreatorResponse>("/api/creators/instagram", {
          identifier: externalId,
          name: name || undefined,
        });
        creator = result.creator;
        setResolvedInstagram(result.instagram_account);
      } else {
        creator = await post<Creator>("/api/creators", {
          name,
          platform,
          external_id: externalId,
          handle: handle || undefined,
        });
        setResolvedInstagram(null);
      }
      onCreated(creator);
      setName("");
      setExternalId("");
      setHandle("");
    } catch (e) {
      setError(`Could not add account: ${e}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <details className="card onboarding" open>
      <summary>Add a YouTube or Instagram account</summary>
      <p className="muted">Add the account you want to track. YouTube needs a channel ID. Instagram needs the username or ID of the professional account connected to the token in your backend settings. To add another platform for the same person, use the same creator name.</p>
      <form className="creator-form" onSubmit={submit}>
        <label>
          {platform === "instagram" ? "Name to show (optional)" : "Creator name"}
          <input required={platform === "youtube"} maxLength={120} value={name} onChange={(e) => setName(e.target.value)} placeholder={platform === "instagram" ? "Leave blank to use the account name" : "Enter a name"} />
        </label>
        <div className="twocol">
          <label>
            Platform
            <select value={platform} onChange={(e) => { setPlatform(e.target.value as Platform); setResolvedInstagram(null); setError(""); }}>
              <option value="youtube">YouTube</option>
              <option value="instagram">Instagram</option>
            </select>
          </label>
          <label>
            {platform === "youtube" ? "YouTube channel ID" : "Instagram username or account ID"}
            <input required maxLength={120} value={externalId} onChange={(e) => { setExternalId(e.target.value); setResolvedInstagram(null); }} placeholder={platform === "youtube" ? "For example, UC…" : "For example, @username"} />
          </label>
        </div>
        {platform === "youtube" && <label>
          Channel handle (optional)
          <input maxLength={120} value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="@handle" />
        </label>}
        <button className="primary" type="submit" disabled={saving}>{saving ? (platform === "instagram" ? "Checking account…" : "Adding account…") : "Add account"}</button>
        {resolvedInstagram && <p className="notice" role="status">Instagram account @{resolvedInstagram.username} added. Account ID: {resolvedInstagram.id}. Followers: {resolvedInstagram.followers.toLocaleString()}.</p>}
        {error && <p className="error" role="alert">{error}</p>}
      </form>
    </details>
  );
}
