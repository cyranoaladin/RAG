// Generated from packages/contracts/schema. Do not edit manually.
import Ajv2020 from 'ajv/dist/2020.js'
import addFormats from 'ajv-formats'

import type { RetrievalResponse, SearchPayload, ChatPayload, ChatRequest, ChatResponse, InternalIdentity, InternalIdentityEnvelope, PilotRetrievalScopeArtifact, ReviewQueuePayload, ReviewDecisionPayload, ReviewDecisionRequest, ReviewQueueResponse, ReviewDecisionResponse, CollectionProfile, SearchPlan, ResourceCandidate, ArtifactRecord, RoutingDecision, QualityReport, IngestionRun, CoverageSnapshot } from './contracts'
import RetrievalResponseSchema from './schema/retrieval-response.json'
import SearchPayloadSchema from './schema/search-payload.json'
import ChatPayloadSchema from './schema/chat-payload.json'
import ChatRequestSchema from './schema/chat-request.json'
import ChatResponseSchema from './schema/chat-response.json'
import InternalIdentitySchema from './schema/internal-identity.json'
import InternalIdentityEnvelopeSchema from './schema/internal-identity-envelope.json'
import PilotRetrievalScopeArtifactSchema from './schema/pilot-retrieval-scope-artifact.json'
import ReviewQueuePayloadSchema from './schema/review-queue-payload.json'
import ReviewDecisionPayloadSchema from './schema/review-decision-payload.json'
import ReviewDecisionRequestSchema from './schema/review-decision-request.json'
import ReviewQueueResponseSchema from './schema/review-queue-response.json'
import ReviewDecisionResponseSchema from './schema/review-decision-response.json'
import CollectionProfileSchema from './schema/collection-profile.json'
import SearchPlanSchema from './schema/search-plan.json'
import ResourceCandidateSchema from './schema/resource-candidate.json'
import ArtifactRecordSchema from './schema/artifact-record.json'
import RoutingDecisionSchema from './schema/routing-decision.json'
import QualityReportSchema from './schema/quality-report.json'
import IngestionRunSchema from './schema/ingestion-run.json'
import CoverageSnapshotSchema from './schema/coverage-snapshot.json'

const ajv = new Ajv2020({ allErrors: true, strict: false })
addFormats(ajv)
const retrievalResponseValidator = ajv.compile<RetrievalResponse>(RetrievalResponseSchema)
const searchPayloadValidator = ajv.compile<SearchPayload>(SearchPayloadSchema)
const chatPayloadValidator = ajv.compile<ChatPayload>(ChatPayloadSchema)
const chatRequestValidator = ajv.compile<ChatRequest>(ChatRequestSchema)
const chatResponseValidator = ajv.compile<ChatResponse>(ChatResponseSchema)
const internalIdentityValidator = ajv.compile<InternalIdentity>(InternalIdentitySchema)
const internalIdentityEnvelopeValidator = ajv.compile<InternalIdentityEnvelope>(InternalIdentityEnvelopeSchema)
const pilotRetrievalScopeArtifactValidator = ajv.compile<PilotRetrievalScopeArtifact>(PilotRetrievalScopeArtifactSchema)
const reviewQueuePayloadValidator = ajv.compile<ReviewQueuePayload>(ReviewQueuePayloadSchema)
const reviewDecisionPayloadValidator = ajv.compile<ReviewDecisionPayload>(ReviewDecisionPayloadSchema)
const reviewDecisionRequestValidator = ajv.compile<ReviewDecisionRequest>(ReviewDecisionRequestSchema)
const reviewQueueResponseValidator = ajv.compile<ReviewQueueResponse>(ReviewQueueResponseSchema)
const reviewDecisionResponseValidator = ajv.compile<ReviewDecisionResponse>(ReviewDecisionResponseSchema)
const collectionProfileValidator = ajv.compile<CollectionProfile>(CollectionProfileSchema)
const searchPlanValidator = ajv.compile<SearchPlan>(SearchPlanSchema)
const resourceCandidateValidator = ajv.compile<ResourceCandidate>(ResourceCandidateSchema)
const artifactRecordValidator = ajv.compile<ArtifactRecord>(ArtifactRecordSchema)
const routingDecisionValidator = ajv.compile<RoutingDecision>(RoutingDecisionSchema)
const qualityReportValidator = ajv.compile<QualityReport>(QualityReportSchema)
const ingestionRunValidator = ajv.compile<IngestionRun>(IngestionRunSchema)
const coverageSnapshotValidator = ajv.compile<CoverageSnapshot>(CoverageSnapshotSchema)

export const validateRetrievalResponse = (payload: unknown): payload is RetrievalResponse => retrievalResponseValidator(payload) === true

export const validateSearchPayload = (payload: unknown): payload is SearchPayload => searchPayloadValidator(payload) === true

export const validateChatPayload = (payload: unknown): payload is ChatPayload => chatPayloadValidator(payload) === true

export const validateChatRequest = (payload: unknown): payload is ChatRequest => chatRequestValidator(payload) === true

export const validateChatResponse = (payload: unknown): payload is ChatResponse => chatResponseValidator(payload) === true

export const validateInternalIdentity = (payload: unknown): payload is InternalIdentity => internalIdentityValidator(payload) === true

export const validateInternalIdentityEnvelope = (payload: unknown): payload is InternalIdentityEnvelope => internalIdentityEnvelopeValidator(payload) === true

export const validatePilotRetrievalScopeArtifact = (payload: unknown): payload is PilotRetrievalScopeArtifact => pilotRetrievalScopeArtifactValidator(payload) === true

export const validateReviewQueuePayload = (payload: unknown): payload is ReviewQueuePayload => reviewQueuePayloadValidator(payload) === true

export const validateReviewDecisionPayload = (payload: unknown): payload is ReviewDecisionPayload => reviewDecisionPayloadValidator(payload) === true

export const validateReviewDecisionRequest = (payload: unknown): payload is ReviewDecisionRequest => reviewDecisionRequestValidator(payload) === true

export const validateReviewQueueResponse = (payload: unknown): payload is ReviewQueueResponse => reviewQueueResponseValidator(payload) === true && payload.returned === payload.documents.length

export const validateReviewDecisionResponse = (payload: unknown): payload is ReviewDecisionResponse => reviewDecisionResponseValidator(payload) === true

export const validateCollectionProfile = (payload: unknown): payload is CollectionProfile => collectionProfileValidator(payload) === true

export const validateSearchPlan = (payload: unknown): payload is SearchPlan => searchPlanValidator(payload) === true

export const validateResourceCandidate = (payload: unknown): payload is ResourceCandidate => resourceCandidateValidator(payload) === true

export const validateArtifactRecord = (payload: unknown): payload is ArtifactRecord => artifactRecordValidator(payload) === true

export const validateRoutingDecision = (payload: unknown): payload is RoutingDecision => routingDecisionValidator(payload) === true

export const validateQualityReport = (payload: unknown): payload is QualityReport => qualityReportValidator(payload) === true

export const validateIngestionRun = (payload: unknown): payload is IngestionRun => ingestionRunValidator(payload) === true

export const validateCoverageSnapshot = (payload: unknown): payload is CoverageSnapshot => coverageSnapshotValidator(payload) === true
