// Generated from packages/contracts/schema. Do not edit manually.

export type ContractBundle =
  RetrievalRequest | RetrievalResponse | SearchPayload | ChatPayload | ChatRequest | ChatResponse | InternalIdentity;
export type TypeDoc =
  | 'programme_officiel'
  | 'ressource_officielle'
  | 'cours'
  | 'fiche_synthese'
  | 'fiche_methode'
  | 'td'
  | 'tp'
  | 'exercice'
  | 'exercice_corrige'
  | 'devoir'
  | 'devoir_corrige'
  | 'evaluation'
  | 'evaluation_corrigee'
  | 'bac_blanc'
  | 'brevet_blanc'
  | 'annale'
  | 'sujet_zero'
  | 'corrige'
  | 'bareme'
  | 'grille_evaluation'
  | 'grille_grand_oral'
  | 'oral'
  | 'diaporama'
  | 'latex'
  | 'notebook'
  | 'code'
  | 'image'
  | 'scan'
  | 'copie'
  | 'rapport'
  | 'referentiel'
  | 'modalite_examen'
  | 'autre';
export type DesiredDocTypes = TypeDoc[];
export type DifficultyMax = number | null;
export type Intent = 'remediation' | 'revision' | 'exercise' | 'program' | 'exam_prep' | 'context';
export type Notions = string[];
export type Query = string;
export type Hybrid = boolean;
export type IncludeCitations = boolean;
export type K = number;
export type Rerank = boolean;
export type Candidat = 'scolarise' | 'individuel' | 'libre' | 'cned_reglemente' | 'cned_libre' | 'aefe' | 'both';
export type CandidateStatusRef = string | null;
export type Establishment = string | null;
/**
 * @minItems 1
 */
export type Matieres = [string, ...string[]];
export type Needs = string[];
export type NexusGroupId = string | null;
export type NexusOffer = string | null;
export type Niveau =
  'troisieme' | 'seconde' | 'premiere' | 'terminale' | 'cycle4' | 'lycee_gt' | 'voie_generale' | 'voie_technologique';
export type Objective = string | null;
export type OfficialLevelRef = string | null;
export type Options = string[];
export type RiskLevel = ('low' | 'medium' | 'high' | 'critical') | null;
export type SchoolCalendarZone = string | null;
export type SchoolYear = string;
export type Specialites = string[];
export type StatusDetail =
  | 'aefe'
  | 'systeme_francais_hors_aefe'
  | 'systeme_tunisien'
  | 'double_cursus'
  | 'candidat_libre'
  | 'cned_reglemente'
  | 'cned_libre'
  | 'unknown';
export type StatutEnseignement =
  | 'tronc_commun'
  | 'enseignement_commun'
  | 'specialite'
  | 'eds'
  | 'option'
  | 'maths_complementaires'
  | 'maths_expertes'
  | 'snt'
  | 'enseignement_scientifique'
  | 'emc'
  | 'atelier'
  | 'stage'
  | 'remediation'
  | 'examen'
  | 'unknown';
export type StudentId = string | null;
export type TargetPathway = string | null;
export type TeacherConfirmed = boolean;
export type Voie = 'college' | 'generale' | 'technologique' | 'professionnelle' | 'aefe' | 'unknown';
export type Warnings = string[];
export type Zone = string;
export type ChunkId = string;
export type Page = number | null;
export type Rights = string;
export type SourceLabel = string;
export type SourceUri = string;
export type DocId = string;
export type Excerpt = string;
export type Score = number;
export type Title = string | null;
export type Results = RetrievalResult[];
export type Warnings1 = string[];
/**
 * @minItems 1
 */
export type Collections = [string, ...string[]];
export type K1 = number | null;
export type Query1 = string;
/**
 * @minItems 1
 */
export type Collections1 = [string, ...string[]];
export type History = ChatMessage[] | null;
export type Content = string;
export type Role = 'system' | 'user' | 'assistant';
export type Query2 = string;
export type TopK = number | null;
export type AnswerMaxChars = number;
export type Collections2 = string[];
export type History1 = ChatMessage[];
export type IncludeRetrieval = boolean;
export type Query3 = string;
export type TopK1 = number;
export type Answer = string;
export type ChunkId1 = string;
export type DocId1 = string;
export type Page1 = number | null;
export type Rights1 = string;
export type SourceLabel1 = string;
export type SourceUri1 = string;
export type Citations = ChatCitation[];
export type Grounded = boolean;
export type RefusalReason = string | null;
export type RetrievalHits = RetrievalResult[];
export type Warnings2 = string[];
export type Aud = string;
export type Exp = number;
export type Iss = string;
export type Jti = string;
/**
 * Niveau principal du profil
 */
export type Niveau1 =
  'troisieme' | 'seconde' | 'premiere' | 'terminale' | 'cycle4' | 'lycee_gt' | 'voie_generale' | 'voie_technologique';
/**
 * Audience ciblée
 */
export type Audience = 'libre' | 'aefe' | 'tous';
/**
 * Type de candidat
 */
export type Candidat1 = 'scolarise' | 'individuel' | 'libre' | 'cned_reglemente' | 'cned_libre' | 'aefe' | 'both';
/**
 * Matières suivies
 *
 * @minItems 1
 */
export type Matieres1 = [string, ...string[]];
/**
 * Statut pédagogique
 */
export type StatutEnseignement1 =
  | 'tronc_commun'
  | 'enseignement_commun'
  | 'specialite'
  | 'eds'
  | 'option'
  | 'maths_complementaires'
  | 'maths_expertes'
  | 'snt'
  | 'enseignement_scientifique'
  | 'emc'
  | 'atelier'
  | 'stage'
  | 'remediation'
  | 'examen'
  | 'unknown';
/**
 * Parcours de l'élève
 */
export type Voie1 = 'college' | 'generale' | 'technologique' | 'professionnelle' | 'aefe' | 'unknown';
export type Role1 = 'student' | 'teacher' | 'admin' | 'ingest_agent' | 'reviewer';
export type Sub = string;
export type Tenant = string;

export interface RetrievalRequest {
  need: RetrievalNeed;
  retrieval?: RetrievalOptions;
  student_profile: StudentProfile;
}
export interface RetrievalNeed {
  desired_doc_types?: DesiredDocTypes;
  difficulty_max?: DifficultyMax;
  intent: Intent;
  notions?: Notions;
  query: Query;
}
export interface RetrievalOptions {
  hybrid?: Hybrid;
  include_citations?: IncludeCitations;
  k?: K;
  rerank?: Rerank;
}
export interface StudentProfile {
  availability?: Availability;
  candidat: Candidat;
  candidate_status_ref?: CandidateStatusRef;
  establishment?: Establishment;
  matieres: Matieres;
  needs?: Needs;
  nexus_group_id?: NexusGroupId;
  nexus_offer?: NexusOffer;
  niveau: Niveau;
  objective?: Objective;
  official_level_ref?: OfficialLevelRef;
  options?: Options;
  risk_level?: RiskLevel;
  school_calendar_zone?: SchoolCalendarZone;
  school_year: SchoolYear;
  specialites?: Specialites;
  status_detail?: StatusDetail;
  statut_enseignement: StatutEnseignement;
  student_id?: StudentId;
  target_pathway?: TargetPathway;
  teacher_confirmed?: TeacherConfirmed;
  voie: Voie;
  warnings?: Warnings;
  zone: Zone;
}
export interface Availability {
  [k: string]: unknown;
}
export interface RetrievalResponse {
  filters_applied?: FiltersApplied;
  results?: Results;
  warnings?: Warnings1;
}
export interface FiltersApplied {
  [k: string]: unknown;
}
export interface RetrievalResult {
  chunk_id: ChunkId;
  citation?: Citation | null;
  doc_id: DocId;
  excerpt: Excerpt;
  metadata?: Metadata;
  score: Score;
  title?: Title;
}
export interface Citation {
  page?: Page;
  rights: Rights;
  source_label: SourceLabel;
  source_uri: SourceUri;
}
export interface Metadata {
  [k: string]: unknown;
}
/**
 * Browser-to-BFF search input; no identity or server credentials.
 */
export interface SearchPayload {
  collections: Collections;
  k?: K1;
  query: Query1;
}
/**
 * Browser-to-BFF chat input; the BFF alone builds the learner profile.
 */
export interface ChatPayload {
  collections: Collections1;
  history?: History;
  query: Query2;
  top_k?: TopK;
}
export interface ChatMessage {
  content: Content;
  role: Role;
}
export interface ChatRequest {
  answer_max_chars?: AnswerMaxChars;
  collections?: Collections2;
  history?: History1;
  include_retrieval?: IncludeRetrieval;
  query: Query3;
  student_profile: StudentProfile;
  top_k?: TopK1;
}
export interface ChatResponse {
  answer: Answer;
  citations?: Citations;
  grounded?: Grounded;
  refusal_reason?: RefusalReason;
  retrieval_hits?: RetrievalHits;
  warnings?: Warnings2;
}
export interface ChatCitation {
  chunk_id: ChunkId1;
  doc_id: DocId1;
  page?: Page1;
  rights: Rights1;
  source_label: SourceLabel1;
  source_uri: SourceUri1;
}
/**
 * Contrat d'identité métier produit par le cockpit.
 *
 * L'implémentation locale (nexus/contracts) le sérialise et valide strictement.
 */
export interface InternalIdentity {
  aud: Aud;
  exp: Exp;
  iss: Iss;
  jti: Jti;
  niveau: Niveau1;
  pedagogical_profile: PedagogicalProfile;
  role: Role1;
  sub: Sub;
  tenant: Tenant;
}
/**
 * Noyau pedagogique d'une identité interne.
 *
 * Champs volontairement resserrés à ce qui est nécessaire dans le cockpit actuel.
 */
export interface PedagogicalProfile {
  audience: Audience;
  candidat: Candidat1;
  matieres: Matieres1;
  statut_enseignement: StatutEnseignement1;
  voie: Voie1;
}
